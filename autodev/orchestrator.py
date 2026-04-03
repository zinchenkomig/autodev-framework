"""AutoDev Orchestrator — central daemon.

Starts the API server and worker loop together in a single process.
Run via ``autodev start``, ``python -m autodev``, or Docker CMD.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path

import uvicorn
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from autodev.core.config import ProjectConfig, load_config
from autodev.core.models import Agent, AgentLog, AgentStatus, Base, Event, Task, TaskStatus

logger = logging.getLogger(__name__)

_FALLBACK_CONFIG = ProjectConfig(name="AutoDev")


def _safe_load_config(path: str) -> ProjectConfig:
    """Load config from *path*, returning a default if missing."""
    if not Path(path).exists():
        logger.warning("Config file not found: %s — using defaults", path)
        return _FALLBACK_CONFIG
    try:
        return load_config(path)
    except Exception as exc:
        logger.warning("Failed to load config %s: %s — using defaults", path, exc)
        return _FALLBACK_CONFIG


class Orchestrator:
    """Central process. Starts once, runs forever.

    Responsibilities:
    - Create DB tables on startup.
    - Upsert agents from autodev.yaml.
    - Run the FastAPI server (uvicorn) in the background.
    - Run the task worker loop.
    """

    def __init__(
        self,
        config_path: str = "autodev.yaml",
        host: str = "0.0.0.0",
        port: int = 8000,
    ) -> None:
        self.config_path = config_path
        self.host = host
        self.port = port
        self.config = _safe_load_config(config_path)
        self.db_url = os.environ.get(
            "DATABASE_URL",
            "postgresql+asyncpg://autodev:autodev@localhost:5432/autodev",
        )
        self._engine = create_async_engine(self.db_url, echo=False)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)
        self.github_token = os.environ.get("GITHUB_TOKEN", "")
        self._current_runner: ClaudeCodeRunner | None = None
        self._current_task_id: str | None = None

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Boot the system: DB → agents → API + worker (parallel)."""
        # Register self globally for API access
        set_orchestrator(self)

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        logger.info("AutoDev Orchestrator starting…")
        logger.info("Config: %s | DB: %s", self.config_path, self.db_url)

        # 1. Create tables
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables ready")

        # 2. Register agents from config
        await self.register_agents()

        # 3. Run API server + worker loop in parallel
        os.environ.setdefault("AUTODEV_CONFIG", self.config_path)

        from autodev.api.app import app as fastapi_app  # import after env is set

        # Store orchestrator on app state for API access
        fastapi_app.state.orchestrator = self

        uv_config = uvicorn.Config(
            fastapi_app,
            host=self.host,
            port=self.port,
            log_level="info",
        )
        server = uvicorn.Server(uv_config)

        logger.info("Starting API server on %s:%d", self.host, self.port)

        # Check if worker should run (disabled in k8s where claude is not available)
        run_worker = os.environ.get("AUTODEV_RUN_WORKER", "true").lower() == "true"

        if run_worker:
            from autodev.pm_worker import pm_worker_loop
            from autodev.qa_worker import qa_worker_loop
            from autodev.release_worker import release_worker_loop

            logger.info("Starting worker loop + PM worker + Release Manager + QA")
            await asyncio.gather(
                server.serve(),
                self.worker_loop(),
                pm_worker_loop(self._session_factory),
                release_worker_loop(self._session_factory),
                qa_worker_loop(self._session_factory),
            )
        else:
            logger.info("Worker loop disabled (AUTODEV_RUN_WORKER=false)")
            await server.serve()

    # ------------------------------------------------------------------
    # Agent registration
    # ------------------------------------------------------------------

    async def register_agents(self) -> None:
        """Upsert agents from autodev.yaml into the database."""
        async with self._session_factory() as session:
            for agent_cfg in self.config.agents:
                agent_id = agent_cfg.role
                existing = await session.get(Agent, agent_id)
                if existing is None:
                    agent = Agent(
                        id=agent_id,
                        role=agent_cfg.role,
                        status=AgentStatus.IDLE,
                    )
                    session.add(agent)
                    logger.info("Registered agent: %s", agent_id)
                else:
                    # Update role in case it changed (no-op if same)
                    existing.role = agent_cfg.role
                    logger.debug("Agent already registered: %s", agent_id)
            await session.commit()

        # Clean up stuck tasks and agents from previous runs
        await self._cleanup_stuck_state()

    async def _cleanup_stuck_state(self) -> None:
        """Reset tasks stuck in in_progress and agents stuck in working state."""
        async with self._session_factory() as session:
            # Reset all agents to idle
            result = await session.execute(select(Agent).where(Agent.status == AgentStatus.WORKING))
            working_agents = result.scalars().all()
            for agent in working_agents:
                agent.status = AgentStatus.IDLE
                agent.current_task_id = None
                logger.info("Reset stuck agent: %s", agent.id)

            # Reset all in_progress tasks to queued
            result = await session.execute(select(Task).where(Task.status == TaskStatus.IN_PROGRESS))
            stuck_tasks = result.scalars().all()
            for task in stuck_tasks:
                task.status = TaskStatus.QUEUED
                task.assigned_to = None
                logger.info("Reset stuck task: %s", task.id)

            await session.commit()

            if working_agents or stuck_tasks:
                logger.info("Cleanup: reset %d agents, %d tasks", len(working_agents), len(stuck_tasks))

    # ------------------------------------------------------------------
    # Worker loop
    # ------------------------------------------------------------------

    async def worker_loop(self) -> None:
        """Endless loop: pick up queued tasks and process them."""
        logger.info("Worker loop started — polling every 30s")
        while True:
            try:
                task = await self.get_next_task()
                if task:
                    await self.process_task(task)
                else:
                    await asyncio.sleep(30)
            except Exception:
                logger.exception("Unhandled error in worker loop — continuing")
                await asyncio.sleep(5)

    def cancel_current_task(self) -> bool:
        """Cancel the currently running task if any. Returns True if cancelled."""
        if self._current_runner:
            logger.info("Cancelling current task %s", self._current_task_id)
            self._current_runner.cancel()
            return True
        return False

    async def get_next_task(self) -> Task | None:
        """Return the highest-priority queued task with satisfied dependencies."""
        async with self._session_factory() as session:
            # Check if developer agent is enabled
            dev_agent = await session.get(Agent, "developer")
            if dev_agent and not dev_agent.enabled:
                return None  # Don't pick up tasks when disabled

            # Get all queued tasks ordered by priority
            result = await session.execute(
                select(Task).where(Task.status == TaskStatus.QUEUED).order_by(Task.priority, Task.created_at)
            )
            queued_tasks = result.scalars().all()

            # Find first task with satisfied dependencies
            for task in queued_tasks:
                if await self._dependencies_satisfied(session, task):
                    await session.refresh(task)
                    return task

            return None

    async def _dependencies_satisfied(self, session: AsyncSession, task: Task) -> bool:
        """Check if all task dependencies are completed (review or later)."""
        if not task.depends_on:
            return True

        # Statuses that mean dependency is "done enough" to proceed
        completed_statuses = {
            TaskStatus.AUTOREVIEW,
            TaskStatus.READY_TO_RELEASE,
            TaskStatus.RELEASED,
        }

        for dep_id in task.depends_on:
            dep_task = await session.get(Task, dep_id)
            if dep_task is None:
                logger.warning("Dependency %s not found for task %s", dep_id, task.id)
                continue  # Missing dependency - allow to proceed
            if dep_task.status not in completed_statuses:
                return False

        return True

    async def _load_dependency_context(self, task: Task) -> str:
        """Load context from completed dependency tasks (e.g. backend PR for frontend task).

        Fetches the PR diff from dependent tasks to give developer full context
        about what the other repo implemented.
        """
        if not task.depends_on:
            return ""

        import httpx

        parts = []
        async with self._session_factory() as session:
            for dep_id in task.depends_on:
                dep_task = await session.get(Task, dep_id)
                if dep_task is None or not dep_task.pr_url:
                    continue

                # Only load cross-repo dependencies (e.g. backend context for frontend task)
                if dep_task.repo == task.repo:
                    continue

                # Fetch PR diff from GitHub
                try:
                    # Extract repo and PR number
                    pr_parts = dep_task.pr_url.rstrip("/").split("/")
                    repo = f"{pr_parts[-4]}/{pr_parts[-3]}"
                    pr_number = pr_parts[-1]

                    async with httpx.AsyncClient() as client:
                        # Get PR files
                        resp = await client.get(
                            f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files",
                            headers={"Authorization": f"token {self.github_token}"},
                            timeout=15.0,
                        )
                        if resp.status_code != 200:
                            continue

                        files = resp.json()

                        # Build context from patches
                        dep_context = f"## Dependency: {dep_task.title}\n"
                        dep_context += f"Repository: {dep_task.repo}\n"
                        dep_context += f"PR: {dep_task.pr_url}\n\n"
                        dep_context += "### Changes made:\n"

                        for f in files:
                            dep_context += f"\n#### {f['filename']}\n"
                            if "patch" in f:
                                dep_context += f"```diff\n{f['patch'][:3000]}\n```\n"

                        parts.append(dep_context)

                except Exception as e:
                    logger.warning(f"Failed to load dependency context for {dep_task.id}: {e}")

        if not parts:
            return ""

        return "--- DEPENDENCY CONTEXT (from related tasks in other repos) ---\n\n" + "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Task processing
    # ------------------------------------------------------------------

    async def process_task(self, task: Task) -> None:
        """Process a single task with Developer-Critic iteration loop."""
        task_id = str(task.id)
        repo_name = task.repo or ""

        # Map short names to full repo names
        if self.config and self.config.repos:
            for repo_cfg in self.config.repos:
                if repo_name in (repo_cfg.name, repo_cfg.name.split("/")[-1]):
                    repo_name = repo_cfg.name
                    break
        _REPO_ALIASES = {"backend": "great_alerter_backend", "frontend": "great_alerter_frontend"}
        if repo_name in _REPO_ALIASES:
            repo_name = _REPO_ALIASES[repo_name]

        workdir = f"/tmp/autodev-{task_id}"
        branch = f"autodev-{task_id}"
        logger.info("Processing task %s: %s (repo=%s)", task_id, task.title, repo_name)

        # Extract restart feedback from description (if task was restarted from staging)
        restart_feedback = ""
        description = task.description or ""
        if "⚠️ **Restart feedback:**" in description:
            parts = description.split("⚠️ **Restart feedback:**", 1)
            feedback_text = parts[1].split("(Restarted from staging")[0].strip()
            restart_feedback = feedback_text
            # Clean description = original part only
            description = parts[0].rstrip().rstrip("-").rstrip()

        final_status = TaskStatus.FAILED
        pr_number: int | None = None
        pr_url: str | None = None

        # 1. Mark in_progress
        await self._update_task_status(task_id, TaskStatus.IN_PROGRESS)
        await self._update_agent_status("developer", AgentStatus.WORKING, task_id)
        await self._log(
            "developer",
            task_id,
            "info",
            f"🚀 Started processing task: {task.title}",
            details=f"Repository: {repo_name or 'N/A'}\nDescription: {task.description or 'No description'}",
        )

        # Reuse existing branch if task already has one (QA return, conflict resolution)
        has_existing_branch = bool(task.branch)
        is_conflict_resolution = has_existing_branch
        existing_branch = task.branch if has_existing_branch else None

        try:
            # 2. Clone repo
            if repo_name:
                if Path(workdir).exists():
                    await self._run_shell(f"rm -rf {workdir}", timeout=30)

                clone_url = (
                    f"https://x-access-token:{self.github_token}@github.com/{repo_name}.git"
                    if self.github_token
                    else f"https://github.com/{repo_name}.git"
                )
                await self._log("developer", task_id, "info", f"Cloning repo {repo_name}...")
                await self._run_shell(
                    f"git clone -b stage {clone_url} {workdir} || git clone {clone_url} {workdir}",
                    timeout=120,
                )
            else:
                Path(workdir).mkdir(parents=True, exist_ok=True)

            # 3. Create or checkout branch
            if repo_name:
                if existing_branch:
                    # Conflict resolution: checkout existing branch and merge stage
                    await self._log(
                        "developer",
                        task_id,
                        "info",
                        f"Checking out existing branch {existing_branch} for conflict resolution...",
                    )
                    await self._run_shell(f"git -C {workdir} fetch origin {existing_branch}", timeout=30)
                    await self._run_shell(f"git -C {workdir} checkout {existing_branch}", timeout=30)

                    # Merge stage — this will create conflict markers
                    try:
                        await self._run_shell(f"git -C {workdir} merge origin/stage --no-edit", timeout=30)
                        await self._log(
                            "developer",
                            task_id,
                            "info",
                            "Merge from stage succeeded (no conflicts)",
                        )
                    except Exception:
                        await self._log(
                            "developer",
                            task_id,
                            "warning",
                            "Merge conflicts detected — Claude Code will resolve them",
                        )

                    branch = existing_branch
                else:
                    await self._run_shell(f"git -C {workdir} checkout -b {branch}", timeout=30)
                    await self._log("developer", task_id, "info", f"Created branch {branch}")

            # 4. Load context
            claude_md = Path(workdir) / "CLAUDE.md"
            context = claude_md.read_text(encoding="utf-8", errors="replace") if claude_md.exists() else ""

            # 4b. For frontend repos: regenerate API client from backend OpenAPI spec
            is_frontend = "frontend" in repo_name
            if is_frontend:
                try:
                    await self._log(
                        "developer",
                        task_id,
                        "info",
                        "Regenerating API client from backend OpenAPI spec...",
                    )

                    # Determine backend branch: from dependency task or develop
                    backend_repo = repo_name.replace("frontend", "backend")
                    backend_branch = "stage"

                    if task.depends_on:
                        async with self._session_factory() as dep_session:
                            for dep_id in task.depends_on:
                                dep_task = await dep_session.get(Task, dep_id)
                                if dep_task and dep_task.branch and "backend" in (dep_task.repo or ""):
                                    backend_branch = dep_task.branch
                                    break

                    await self._log("developer", task_id, "info", f"Using backend branch: {backend_branch}")

                    # Clone backend, extract OpenAPI spec
                    backend_clone_url = f"https://x-access-token:{self.github_token}@github.com/{backend_repo}.git"
                    backend_tmpdir = f"/tmp/autodev-backend-{task_id[:8]}"

                    await self._run_shell(f"rm -rf {backend_tmpdir}", timeout=10)
                    await self._run_shell(
                        f"git clone -b {backend_branch} --depth 1 {backend_clone_url} {backend_tmpdir} "
                        f"|| git clone -b stage --depth 1 {backend_clone_url} {backend_tmpdir}",
                        timeout=60,
                    )

                    # Generate OpenAPI spec (needs dummy postgres env to satisfy Settings)
                    await self._run_shell(
                        f"cd {backend_tmpdir} && uv sync --frozen 2>&1 | tail -1 && "
                        f"mkdir -p {workdir}/openapi && "
                        f"POSTGRES__HOST=localhost POSTGRES__PORT=5432 POSTGRES__USER=x POSTGRES__PASSWORD=x POSTGRES__DB=x "
                        f'uv run python -c "'
                        f"from src.backend.main import app; "
                        f"import json; "
                        f"json.dump(app.openapi(), open('{workdir}/openapi/openapi.json', 'w'), indent=2)"
                        f'"',
                        timeout=120,
                    )

                    await self._run_shell(f"rm -rf {backend_tmpdir}", timeout=10)

                    # Run orval to regenerate API client
                    await self._run_shell(
                        f"cd {workdir} && npm install --silent 2>&1 | tail -1 && npm run gen:api 2>&1 | tail -1",
                        timeout=120,
                    )
                    await self._log("developer", task_id, "info", "API client regenerated ✅")
                except Exception as e:
                    await self._log(
                        "developer",
                        task_id,
                        "warning",
                        f"Failed to regenerate API client: {e}. Developer will use existing generated.ts.",
                    )

            # 4c. Load dependency context (e.g. backend PR for frontend task)
            dep_context = await self._load_dependency_context(task)

            from autodev.core.runner import ClaudeCodeRunner

            runner = ClaudeCodeRunner(model="claude-sonnet-4-20250514", timeout=1800)  # 30 minutes
            self._current_runner = runner
            self._current_task_id = task_id

            # ========== PHASE 1: PLANNING ==========
            await self._log("developer", task_id, "info", "Phase 1: Creating implementation plan...")

            feedback_block = ""
            if restart_feedback:
                feedback_block = (
                    f"\n🚨 CRITICAL — USER FEEDBACK (this task was rejected from staging and must address this):\n"
                    f"{restart_feedback}\n"
                    f"The previous implementation FAILED to satisfy the user. Your plan MUST specifically address this feedback.\n"
                )

            # ========== PHASE 1-2: PLANNING DISCUSSION (developer ↔ critic) ==========
            MAX_PLAN_ITERATIONS = 3
            plan = ""
            plan_feedback = ""
            plan_approved = False
            discussion_history = ""

            for plan_iter in range(MAX_PLAN_ITERATIONS):
                # --- Developer creates/revises plan ---
                if plan_iter == 0:
                    await self._log("developer", task_id, "info", "Phase 1: Creating implementation plan...")
                    plan_prompt = f"""You are a senior developer. Analyze this task and create a detailed implementation plan.

TASK: {task.title}
DESCRIPTION: {description}
{feedback_block}
{f"--- Project Context ---{chr(10)}{context}" if context else ""}

{dep_context}

Create a plan that includes:
1. Files that need to be created or modified
2. Key functions/classes to implement
3. Potential edge cases or risks
4. Testing approach

DO NOT write any code yet. Just the plan in markdown format."""
                else:
                    await self._log(
                        "developer", task_id, "info", f"Phase 1: Revising plan (iteration {plan_iter + 1})..."
                    )
                    plan_prompt = f"""You are a senior developer. Revise your implementation plan based on the critic's feedback.

TASK: {task.title}
DESCRIPTION: {description}
{feedback_block}

{discussion_history}

CRITIC'S LATEST FEEDBACK:
{plan_feedback}

Revise the plan to address the feedback. Keep what's good, fix what was criticized.
DO NOT write any code yet. Just the revised plan in markdown format."""

                plan_result = await runner.run(plan_prompt, context={"workdir": workdir})
                plan = plan_result.output
                await self._log(
                    "developer",
                    task_id,
                    "info",
                    f"📋 Plan {'created' if plan_iter == 0 else 'revised'} ({len(plan)} chars, {plan_result.duration_seconds:.1f}s)",
                    details=f"=== PLAN v{plan_iter + 1} ===\n\n{plan}",
                )

                # --- Critic reviews plan ---
                await self._log(
                    "developer", task_id, "info", f"Phase 2: Critic reviewing plan (iteration {plan_iter + 1})..."
                )

                critic_plan_prompt = f"""You are a senior code reviewer and architect. Review this implementation plan.

TASK: {task.title}
DESCRIPTION: {description}
{feedback_block}

{"DISCUSSION SO FAR:" + chr(10) + discussion_history if discussion_history else ""}

PROPOSED PLAN (v{plan_iter + 1}):
{plan}

Review for:
1. Missing considerations
2. Potential bugs or edge cases not addressed
3. Better approaches if any
4. Security concerns
{"5. Does the plan specifically address the user's rejection feedback?" if restart_feedback else ""}

If the plan is good and ready for implementation, respond with: APPROVED

If there are issues, respond with:
FEEDBACK:
- [your feedback points]"""

                critic_result = await runner.run(critic_plan_prompt, context={"workdir": workdir})
                plan_feedback = critic_result.output
                plan_approved = "APPROVED" in plan_feedback.upper() and "FEEDBACK:" not in plan_feedback.upper()

                await self._log(
                    "developer",
                    task_id,
                    "info" if plan_approved else "warning",
                    f"🔍 Plan review #{plan_iter + 1}: {'✅ Approved' if plan_approved else '⚠️ Feedback received'} ({critic_result.duration_seconds:.1f}s)",
                    details=f"=== CRITIC REVIEW v{plan_iter + 1} ===\n\n{plan_feedback}",
                )

                # Build discussion history for next iteration
                discussion_history += f"\n--- Plan v{plan_iter + 1} (summary) ---\n{plan[:2000]}\n"
                discussion_history += f"\n--- Critic feedback #{plan_iter + 1} ---\n{plan_feedback[:2000]}\n"

                if plan_approved:
                    break

            # ========== PHASE 3: IMPLEMENTATION ==========
            await self._log("developer", task_id, "info", "Phase 3: Implementing solution...")

            impl_prompt = f"""You are a senior developer. Implement the solution based on the approved plan.

TASK: {task.title}
DESCRIPTION: {description}
{feedback_block}
FINAL PLAN:
{plan}

{f"NOTE: Plan was approved after {plan_iter + 1} revision(s). Key discussion points:{chr(10)}{discussion_history[-3000:]}" if plan_iter > 0 else ""}

{f"--- Project Context ---{chr(10)}{context}" if context else ""}

{dep_context}

## CRITICAL REQUIREMENTS:
1. The implementation MUST be fully functional end-to-end
2. Do NOT leave placeholder comments like "TODO" or "will be added later"
3. Do NOT comment out functionality — either implement it or don't include it
4. If you add UI controls, they MUST actually do something when used
5. Verify your changes work by checking imports, function calls, and data flow
{"6. FRONTEND: Use ONLY hooks and types from src/api/generated.ts (generated by Orval from OpenAPI). NEVER write custom API hooks or manually define API types. Import from @/api/generated." if is_frontend else "6. Ensure API endpoints and DTOs are consistent."}

Now implement the solution. Create/modify files as needed."""

            impl_result = await runner.run(impl_prompt, context={"workdir": workdir})

            await self._log(
                "developer",
                task_id,
                "info" if impl_result.status == "success" else "error",
                f"🛠️ Implementation {'completed' if impl_result.status == 'success' else 'failed'} ({impl_result.duration_seconds:.1f}s)",
                details=f"=== DEVELOPER OUTPUT ===\n\n{impl_result.output[:10000] if impl_result.output else 'No output'}",
            )

            if impl_result.status != "success":
                raise RuntimeError(f"Implementation failed: {impl_result.output}")

            # ========== PHASE 4: CODE REVIEW LOOP ==========
            MAX_REVIEW_ITERATIONS = 3
            code_approved = False

            for iteration in range(MAX_REVIEW_ITERATIONS):
                await self._log(
                    "developer",
                    task_id,
                    "info",
                    f"Phase 4: Code review (iteration {iteration + 1}/{MAX_REVIEW_ITERATIONS})...",
                )

                # Get current diff
                try:
                    diff_output = await self._run_shell(
                        f"git -C {workdir} add -A && git -C {workdir} diff --cached",
                        timeout=30,
                        capture=True,
                    )
                except Exception:
                    diff_output = ""

                if not diff_output.strip():
                    await self._log("developer", task_id, "warning", "No changes to review")
                    break

                # Critic reviews code
                feedback_review_note = ""
                if restart_feedback:
                    feedback_review_note = (
                        f"\n🚨 USER FEEDBACK (task was rejected from staging — this MUST be addressed):\n"
                        f"{restart_feedback}\n"
                        f"If the diff does NOT address this feedback, it is a MUST_FIX.\n"
                    )

                review_prompt = f"""You are a senior code reviewer. Review this code change.

TASK: {task.title}
TASK DESCRIPTION: {description}
{feedback_review_note}
CODE DIFF:
```diff
{diff_output[:15000]}
```

Review for:
1. **Does it actually solve the task?** — Check if the feature works end-to-end, not just partially
2. **Dead code / placeholders** — Any TODO comments, commented-out code, or "will be added later"?
3. **Integration** — If it's a frontend change, does it call the backend API correctly? If backend, does the endpoint exist?
4. **Bugs or logic errors**
5. **Missing error handling**
{"6. **User feedback compliance** — Does the change specifically address the user's rejection feedback above?" if restart_feedback else ""}

CRITICAL: If the code adds UI controls that don't actually do anything, or leaves functionality commented out with "TODO" — this is a MUST_FIX.

If the code is ready to merge, respond with: APPROVED

If there are critical issues, respond with:
MUST_FIX:
- [critical issues]

Be pragmatic but thorough — half-implemented features are worse than no feature."""

                review_result = await runner.run(review_prompt, context={"workdir": workdir})
                review_feedback = review_result.output

                code_approved = "APPROVED" in review_feedback.upper() and "MUST_FIX:" not in review_feedback.upper()

                await self._log(
                    "developer",
                    task_id,
                    "info" if code_approved else "warning",
                    f"🔍 Code review #{iteration + 1}: {'✅ Approved' if code_approved else '⚠️ Changes requested'} ({review_result.duration_seconds:.1f}s)",
                    details=f"=== CODE REVIEW #{iteration + 1} ===\n\nDiff size: {len(diff_output)} chars\n\n{review_feedback}",
                )

                if code_approved:
                    break

                # Developer fixes issues
                if iteration < MAX_REVIEW_ITERATIONS - 1:
                    await self._log("developer", task_id, "info", "Addressing review feedback...")

                    fix_prompt = f"""Fix the issues found in code review.

TASK: {task.title}

REVIEW FEEDBACK:
{review_feedback}

Address the MUST_FIX issues. Make the necessary changes."""

                    fix_result = await runner.run(fix_prompt, context={"workdir": workdir})
                    await self._log(
                        "developer",
                        task_id,
                        "info",
                        f"🔧 Fixes applied ({fix_result.duration_seconds:.1f}s)",
                        details=f"=== FIX ITERATION #{iteration + 1} ===\n\n{fix_result.output[:5000] if fix_result.output else 'No output'}",
                    )

            self._current_runner = None

            # ========== PHASE 5: COMMIT & PR ==========
            if repo_name:
                await self._run_shell(f"git -C {workdir} add -A", timeout=30)

                has_changes = False
                try:
                    await self._run_shell(f"git -C {workdir} diff --cached --quiet", timeout=30)
                except Exception:
                    has_changes = True

                if has_changes:
                    if is_conflict_resolution:
                        commit_msg = f"fix: resolve merge conflicts [autodev-{task_id[:8]}]"
                    else:
                        commit_msg = f"feat: {task.title[:72]} [autodev-{task_id[:8]}]"
                    await self._log("developer", task_id, "info", "Committing and pushing changes...")

                    await self._run_shell(
                        f'git -C {workdir} commit -m "{commit_msg}" && git -C {workdir} push -u origin {branch}',
                        timeout=60,
                    )

                    # Get file stats for PR description
                    try:
                        diff_stat = await self._run_shell(
                            f"git -C {workdir} diff --stat HEAD~1", timeout=15, capture=True
                        )
                    except Exception:
                        diff_stat = ""

                    # Generate concise PR summary via LLM
                    summary_prompt = f"""Write a concise PR description (2-3 sentences) for this change.

Task: {task.title}
Description: {task.description or "N/A"}

Key changes (from diff stats):
{diff_stat[:500] if diff_stat else "N/A"}

Implementation notes:
{impl_result.output[:1000] if impl_result and impl_result.output else "N/A"}

Write ONLY the summary. No headers, no markdown formatting. Just 2-3 sentences in Russian about what was done and any notable implementation details."""

                    try:
                        summary_result = await runner.run(summary_prompt, context={"workdir": workdir})
                        pr_summary = summary_result.output.strip()[:500]
                    except Exception:
                        pr_summary = task.description or task.title

                    # Build compact PR description
                    pr_body = f"{pr_summary}\n\n"
                    if diff_stat:
                        pr_body += f"```\n{diff_stat[:800]}\n```\n\n"
                    pr_body += f"---\n*AutoDev task `{task_id[:8]}`*"

                    if is_conflict_resolution:
                        # PR already exists — just log, CI will re-run
                        pr_number = task.pr_number
                        pr_url = task.pr_url
                        await self._log(
                            "developer",
                            task_id,
                            "info",
                            f"Conflicts resolved, pushed to existing PR: {pr_url}",
                        )
                    else:
                        await self._log("developer", task_id, "info", f"Creating PR for branch {branch}...")
                        pr_number = await self._create_pr(
                            repo=repo_name,
                            branch=branch,
                            title=task.title,
                            body=pr_body,
                        )
                        if pr_number:
                            pr_url = f"https://github.com/{repo_name}/pull/{pr_number}"
                            await self._log("developer", task_id, "info", f"PR #{pr_number} created: {pr_url}")
                else:
                    await self._log("developer", task_id, "warning", "No changes to commit")

            # Final status
            if code_approved or (not code_approved and iteration >= MAX_REVIEW_ITERATIONS - 1 and has_changes):
                final_status = TaskStatus.AUTOREVIEW
                if not code_approved:
                    await self._log(
                        "developer",
                        task_id,
                        "warning",
                        "Max iterations reached - sending to human review",
                    )
            else:
                final_status = TaskStatus.FAILED

            await self._update_task_status(task_id, final_status, pr_number=pr_number, pr_url=pr_url, branch=branch)
            await self._log(
                "developer",
                task_id,
                "info",
                f"{'✅' if final_status == TaskStatus.AUTOREVIEW else '❌'} Task completed: {final_status}",
                details=f"PR: {pr_url or 'N/A'}\nCode approved by critic: {code_approved}",
            )

            # Emit events
            await self._emit_event("task.completed", {"task_id": task_id, "status": str(final_status)})
            if pr_number:
                await self._emit_event("pr.created", {"task_id": task_id, "pr_number": pr_number, "repo": repo_name})

        except Exception as exc:
            logger.exception("Task %s failed with exception", task_id)
            await self._log("developer", task_id, "error", f"Task failed: {exc}")
            await self._update_task_status(task_id, TaskStatus.FAILED)
            await self._emit_event("task.failed", {"task_id": task_id, "error": str(exc)})
            final_status = TaskStatus.FAILED

            # Notify about failure
            try:
                await notify_task_status(task_id, task.title, "failed", error=str(exc))
            except Exception as notify_err:
                logger.warning(f"Failed to send failure notification: {notify_err}")

        else:
            # Notify about success (only if no exception)
            try:
                await notify_task_status(
                    task_id,
                    task.title,
                    "review" if final_status == TaskStatus.AUTOREVIEW else "failed",
                    pr_url=pr_url or "",
                )
            except Exception as notify_err:
                logger.warning(f"Failed to send notification: {notify_err}")

        finally:
            await self._update_agent_status("developer", AgentStatus.IDLE, None)
            self._current_runner = None
            self._current_task_id = None

            if Path(workdir).exists():
                shutil.rmtree(workdir, ignore_errors=True)

    # Helpers
    # ------------------------------------------------------------------

    async def _update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        pr_number: int | None = None,
        pr_url: str | None = None,
        branch: str | None = None,
    ) -> None:
        import uuid as _uuid

        async with self._session_factory() as session:
            try:
                pk = _uuid.UUID(task_id)
            except ValueError:
                pk = task_id  # type: ignore[assignment]
            task = await session.get(Task, pk)
            if task:
                task.status = status
                if pr_number is not None:
                    task.pr_number = pr_number
                if pr_url is not None:
                    task.pr_url = pr_url
                if branch is not None:
                    task.branch = branch
                await session.commit()

    async def _update_agent_status(
        self,
        agent_id: str,
        status: AgentStatus,
        task_id: str | None,
    ) -> None:
        import uuid as _uuid

        async with self._session_factory() as session:
            agent = await session.get(Agent, agent_id)
            if agent:
                agent.status = status
                if task_id is not None:
                    try:
                        agent.current_task_id = _uuid.UUID(task_id)
                    except ValueError:
                        pass
                else:
                    agent.current_task_id = None
                await session.commit()

    async def _log(
        self,
        agent_id: str,
        task_id: str | None,
        level: str,
        message: str,
        details: str | None = None,
    ) -> None:
        """Persist an AgentLog entry to the database."""
        import uuid as _uuid

        async with self._session_factory() as session:
            tid: _uuid.UUID | None = None
            if task_id is not None:
                try:
                    tid = _uuid.UUID(task_id)
                except ValueError:
                    pass
            log = AgentLog(
                agent_id=agent_id,
                task_id=tid,
                level=level,
                message=message,
                details=details,
            )
            session.add(log)
            await session.commit()

    async def _emit_event(self, event_type: str, payload: dict) -> None:
        async with self._session_factory() as session:
            event = Event(type=event_type, payload=payload, source="orchestrator")
            session.add(event)
            await session.commit()
            logger.info("Event emitted: %s %s", event_type, payload)

    async def _run_shell(self, cmd: str, timeout: int = 60, capture: bool = False) -> str:
        """Run a shell command, raising on failure. If capture=True, return stdout."""
        logger.debug("Shell: %s", cmd)
        proc = await asyncio.create_subprocess_exec(
            "/bin/bash",
            "-c",
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError(f"Command timed out after {timeout}s: {cmd}")
        stdout = stdout_b.decode(errors="replace").strip()
        stderr = stderr_b.decode(errors="replace").strip()
        if proc.returncode != 0 and not capture:
            raise RuntimeError(f"Command failed (rc={proc.returncode}): {cmd}\nstdout={stdout}\nstderr={stderr}")
        return stdout

    async def _create_pr(
        self,
        repo: str,
        branch: str,
        title: str,
        body: str,
    ) -> int | None:
        """Create a GitHub PR and return the PR number, or None on failure."""
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            logger.warning("GITHUB_TOKEN not set — skipping PR creation")
            return None

        from autodev.integrations.github import GitHubClient

        # repo may already include owner (e.g. "zinchenkomig/great_alerter_backend")
        full_repo = repo if "/" in repo else f"zinchenkomig/{repo}"
        client = GitHubClient(token=token, default_repo=full_repo)
        try:
            pr = await client.create_pr(
                title=title,
                body=body,
                head=branch,
                base="stage",
            )
            pr_number = pr.get("number")
            logger.info("PR created: #%s for %s", pr_number, repo)
            return pr_number
        except Exception as exc:
            logger.warning("Failed to create PR for %s: %s", repo, exc)
            return None


# ---------------------------------------------------------------------------
# Module entry point: python -m autodev.orchestrator
# ---------------------------------------------------------------------------

# Global orchestrator instance for API access
_orchestrator = None  # type: Orchestrator | None


def get_orchestrator():
    """Get the global orchestrator instance."""
    return _orchestrator


def set_orchestrator(orch):
    """Set the global orchestrator instance."""
    global _orchestrator
    _orchestrator = orch


if __name__ == "__main__":
    orch = Orchestrator()
    set_orchestrator(orch)
    asyncio.run(orch.start())


# ============ Telegram Notifications ============


async def notify_task_status(task_id: str, title: str, status: str, error: str = "", pr_url: str = "") -> None:
    """Send Telegram notification and create alert for task status changes."""
    # 1. Notify user via Telegram bot
    try:
        from autodev.integrations.telegram_pm import get_telegram_bot

        bot = await get_telegram_bot()

        if status == "failed":
            await bot.notify_task_failed(task_id, title, error)
        elif status == "review":
            await bot.notify_task_ready_for_review(task_id, title, pr_url)
    except Exception as e:
        logger.warning(f"Failed to send Telegram notification: {e}")

    # 2. Create alert for failed tasks (will notify OpenClaw/Brian)
    if status == "failed":
        try:
            await create_alert(
                alert_type="task_failed",
                severity="high",
                title=f"Task failed: {title}",
                message=error[:2000] if error else "No error details",
                source=task_id,
            )
        except Exception as e:
            logger.warning(f"Failed to create alert: {e}")


async def create_alert(alert_type: str, severity: str, title: str, message: str = "", source: str = "") -> None:
    """Create an alert and notify OpenClaw."""
    import os
    from datetime import UTC, datetime
    from uuid import uuid4

    import httpx

    try:
        from autodev.api.database import SessionLocal
        from autodev.core.models import Alert

        async with SessionLocal() as session:
            alert = Alert(
                id=uuid4(),
                type=alert_type,
                severity=severity,
                title=title,
                message=message,
                source=source,
                resolved=False,
                notified=False,
                created_at=datetime.now(UTC),
            )
            session.add(alert)
            await session.commit()
            await session.refresh(alert)

            # Notify OpenClaw
            openclaw_url = os.environ.get("OPENCLAW_URL", "http://localhost:3033")
            chat_id = os.environ.get("OPENCLAW_CHAT_ID", "861853668")

            severity_emoji = {"critical": "🚨", "high": "🔴", "medium": "🟡", "low": "🟢"}
            emoji = severity_emoji.get(severity, "⚠️")

            notify_msg = (
                f"{emoji} **AutoDev Alert** [{severity.upper()}]\n\n**Type:** {alert_type}\n**Title:** {title}\n"
            )
            if message:
                notify_msg += f"\n**Details:**\n```\n{message[:1000]}\n```\n"
            if source:
                notify_msg += f"\n**Source:** {source}"

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{openclaw_url}/api/send",
                    json={
                        "channel": "telegram",
                        "account": "default",
                        "chatId": chat_id,
                        "message": notify_msg,
                    },
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    alert.notified = True
                    await session.commit()

    except Exception as e:
        logger.warning(f"Failed to create alert: {e}")
