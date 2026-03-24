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
        self._current_runner: "ClaudeCodeRunner | None" = None
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
        logger.info("Starting worker loop")

        await asyncio.gather(
            server.serve(),
            self.worker_loop(),
        )

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
                select(Task)
                .where(Task.status == TaskStatus.QUEUED)
                .order_by(Task.priority, Task.created_at)
            )
            queued_tasks = result.scalars().all()
            
            # Find first task with satisfied dependencies
            for task in queued_tasks:
                if await self._dependencies_satisfied(session, task):
                    await session.refresh(task)
                    return task
            
            return None
    
    async def _dependencies_satisfied(self, session: "AsyncSession", task: Task) -> bool:
        """Check if all task dependencies are completed (review or later)."""
        if not task.depends_on:
            return True
        
        # Statuses that mean dependency is "done enough" to proceed
        completed_statuses = {TaskStatus.REVIEW, TaskStatus.READY_TO_RELEASE, TaskStatus.RELEASED}
        
        for dep_id in task.depends_on:
            dep_task = await session.get(Task, dep_id)
            if dep_task is None:
                logger.warning("Dependency %s not found for task %s", dep_id, task.id)
                continue  # Missing dependency - allow to proceed
            if dep_task.status not in completed_statuses:
                return False
        
        return True

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
        
        final_status = TaskStatus.FAILED
        pr_number: int | None = None
        pr_url: str | None = None

        # 1. Mark in_progress
        await self._update_task_status(task_id, TaskStatus.IN_PROGRESS)
        await self._update_agent_status("developer", AgentStatus.WORKING, task_id)
        await self._log("developer", task_id, "info", f"🚀 Started processing task: {task.title}", details=f"Repository: {repo_name or 'N/A'}\nDescription: {task.description or 'No description'}")

        try:
            # 2. Clone repo
            if repo_name:
                if Path(workdir).exists():
                    await self._run_shell(f"rm -rf {workdir}", timeout=30)
                
                clone_url = f"https://x-access-token:{self.github_token}@github.com/{repo_name}.git" if self.github_token else f"https://github.com/{repo_name}.git"
                await self._log("developer", task_id, "info", f"Cloning repo {repo_name}...")
                await self._run_shell(
                    f"git clone -b develop {clone_url} {workdir} || git clone {clone_url} {workdir}",
                    timeout=120,
                )
            else:
                Path(workdir).mkdir(parents=True, exist_ok=True)

            # 3. Create feature branch
            if repo_name:
                await self._run_shell(f"git -C {workdir} checkout -b {branch}", timeout=30)
                await self._log("developer", task_id, "info", f"Created branch {branch}")

            # 4. Load context
            claude_md = Path(workdir) / "CLAUDE.md"
            context = claude_md.read_text(encoding="utf-8", errors="replace") if claude_md.exists() else ""
            
            from autodev.core.runner import ClaudeCodeRunner
            runner = ClaudeCodeRunner(model="claude-sonnet-4-20250514", timeout=600)
            self._current_runner = runner
            self._current_task_id = task_id
            
            # ========== PHASE 1: PLANNING ==========
            await self._log("developer", task_id, "info", "Phase 1: Creating implementation plan...")
            
            plan_prompt = f"""You are a senior developer. Analyze this task and create a detailed implementation plan.

TASK: {task.title}
DESCRIPTION: {task.description or 'No description'}

{f'--- Project Context ---{chr(10)}{context}' if context else ''}

Create a plan that includes:
1. Files that need to be created or modified
2. Key functions/classes to implement
3. Potential edge cases or risks
4. Testing approach

DO NOT write any code yet. Just the plan in markdown format."""

            plan_result = await runner.run(plan_prompt, context={"workdir": workdir})
            plan = plan_result.output
            await self._log(
                "developer", task_id, "info", 
                f"📋 Plan created ({len(plan)} chars, {plan_result.duration_seconds:.1f}s)",
                details=f"=== IMPLEMENTATION PLAN ===\n\n{plan}"
            )
            
            # ========== PHASE 2: CRITIC REVIEWS PLAN ==========
            await self._log("developer", task_id, "info", "Phase 2: Critic reviewing plan...")
            
            critic_plan_prompt = f"""You are a senior code reviewer and architect. Review this implementation plan.

TASK: {task.title}

PROPOSED PLAN:
{plan}

Review for:
1. Missing considerations
2. Potential bugs or edge cases not addressed  
3. Better approaches if any
4. Security concerns

If the plan is good, respond with: APPROVED

If there are issues, respond with:
FEEDBACK:
- [your feedback points]"""

            critic_result = await runner.run(critic_plan_prompt, context={"workdir": workdir})
            plan_feedback = critic_result.output
            plan_approved = "APPROVED" in plan_feedback.upper() and "FEEDBACK:" not in plan_feedback.upper()
            
            await self._log(
                "developer", task_id, 
                "info" if plan_approved else "warning",
                f"🔍 Plan review: {'✅ Approved' if plan_approved else '⚠️ Feedback received'} ({critic_result.duration_seconds:.1f}s)",
                details=f"=== CRITIC PLAN REVIEW ===\n\n{plan_feedback}"
            )
            
            # ========== PHASE 3: IMPLEMENTATION ==========
            await self._log("developer", task_id, "info", "Phase 3: Implementing solution...")
            
            impl_prompt = f"""You are a senior developer. Implement the solution based on this plan.

TASK: {task.title}
DESCRIPTION: {task.description or 'No description'}

PLAN:
{plan}

{f'REVIEWER FEEDBACK:{chr(10)}{plan_feedback}' if not plan_approved else ''}

{f'--- Project Context ---{chr(10)}{context}' if context else ''}

Now implement the solution. Create/modify files as needed.
Follow the plan and address any reviewer feedback."""

            impl_result = await runner.run(impl_prompt, context={"workdir": workdir})
            
            await self._log(
                "developer", task_id,
                "info" if impl_result.status == "success" else "error",
                f"🛠️ Implementation {'completed' if impl_result.status == 'success' else 'failed'} ({impl_result.duration_seconds:.1f}s)",
                details=f"=== DEVELOPER OUTPUT ===\n\n{impl_result.output[:10000] if impl_result.output else 'No output'}"
            )
            
            if impl_result.status != "success":
                raise RuntimeError(f"Implementation failed: {impl_result.output}")
            
            # ========== PHASE 4: CODE REVIEW LOOP ==========
            MAX_REVIEW_ITERATIONS = 3
            code_approved = False
            
            for iteration in range(MAX_REVIEW_ITERATIONS):
                await self._log("developer", task_id, "info", f"Phase 4: Code review (iteration {iteration + 1}/{MAX_REVIEW_ITERATIONS})...")
                
                # Get current diff
                try:
                    diff_output = await self._run_shell(
                        f"git -C {workdir} add -A && git -C {workdir} diff --cached",
                        timeout=30, capture=True
                    )
                except Exception:
                    diff_output = ""
                
                if not diff_output.strip():
                    await self._log("developer", task_id, "warning", "No changes to review")
                    break
                
                # Critic reviews code
                review_prompt = f"""You are a senior code reviewer. Review this code change.

TASK: {task.title}

CODE DIFF:
```diff
{diff_output[:15000]}
```

Review for:
1. Bugs or logic errors
2. Code style and best practices
3. Missing error handling
4. Security issues

If the code is ready to merge, respond with: APPROVED

If there are critical issues, respond with:
MUST_FIX:
- [critical issues]

Be pragmatic - approve if it works correctly."""

                review_result = await runner.run(review_prompt, context={"workdir": workdir})
                review_feedback = review_result.output
                
                code_approved = "APPROVED" in review_feedback.upper() and "MUST_FIX:" not in review_feedback.upper()
                
                await self._log(
                    "developer", task_id,
                    "info" if code_approved else "warning",
                    f"🔍 Code review #{iteration + 1}: {'✅ Approved' if code_approved else '⚠️ Changes requested'} ({review_result.duration_seconds:.1f}s)",
                    details=f"=== CODE REVIEW #{iteration + 1} ===\n\nDiff size: {len(diff_output)} chars\n\n{review_feedback}"
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
                        "developer", task_id, "info", 
                        f"🔧 Fixes applied ({fix_result.duration_seconds:.1f}s)",
                        details=f"=== FIX ITERATION #{iteration + 1} ===\n\n{fix_result.output[:5000] if fix_result.output else 'No output'}"
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
                    commit_msg = f"feat: {task.title[:72]} [autodev-{task_id[:8]}]"
                    await self._log("developer", task_id, "info", "Committing and pushing changes...")
                    await self._run_shell(
                        f'git -C {workdir} commit -m "{commit_msg}" && git -C {workdir} push -u origin {branch}',
                        timeout=60,
                    )

                    await self._log("developer", task_id, "info", f"Creating PR for branch {branch}...")
                    pr_number = await self._create_pr(
                        repo=repo_name, branch=branch, title=task.title,
                        body=f"Automated PR for task {task_id}\n\n{task.description or ''}\n\n✅ Reviewed by AI Critic",
                    )
                    if pr_number:
                        pr_url = f"https://github.com/{repo_name}/pull/{pr_number}"
                        await self._log("developer", task_id, "info", f"PR #{pr_number} created: {pr_url}")
                else:
                    await self._log("developer", task_id, "warning", "No changes to commit")

            # Final status
            if code_approved or (not code_approved and iteration >= MAX_REVIEW_ITERATIONS - 1 and has_changes):
                final_status = TaskStatus.REVIEW
                if not code_approved:
                    await self._log("developer", task_id, "warning", "Max iterations reached - sending to human review")
            else:
                final_status = TaskStatus.FAILED
            
            await self._update_task_status(task_id, final_status, pr_number=pr_number, pr_url=pr_url)
            await self._log(
                "developer", task_id, "info", 
                f"{'✅' if final_status == TaskStatus.REVIEW else '❌'} Task completed: {final_status}",
                details=f"PR: {pr_url or 'N/A'}\nCode approved by critic: {code_approved}"
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

        finally:
            await self._update_agent_status("developer", AgentStatus.IDLE, None)
            self._current_runner = None
            self._current_task_id = None
            
            if Path(workdir).exists():
                shutil.rmtree(workdir, ignore_errors=True)

        # Notify
        await notify_task_status(
            task_id, task.title,
            "review" if final_status == TaskStatus.REVIEW else "failed",
            pr_url=pr_url or ""
        )

    # Helpers
    # ------------------------------------------------------------------

    async def _update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        pr_number: int | None = None,
        pr_url: str | None = None,
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
            raise RuntimeError(
                f"Command failed (rc={proc.returncode}): {cmd}\nstdout={stdout}\nstderr={stderr}"
            )
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

        client = GitHubClient(token=token, default_repo=f"zinchenkomig/{repo}")
        try:
            pr = await client.create_pr(
                title=title,
                body=body,
                head=branch,
                base="develop",
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
    """Send Telegram notification about task status change."""
    try:
        from autodev.integrations.telegram_pm import get_telegram_bot
        bot = get_telegram_bot()
        
        if status == "failed":
            await bot.notify_task_failed(task_id, title, error)
        elif status == "review":
            await bot.notify_task_ready_for_review(task_id, title, pr_url)
    except Exception as e:
        logger.warning(f"Failed to send Telegram notification: {e}")
