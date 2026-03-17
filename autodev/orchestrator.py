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
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from autodev.core.config import ProjectConfig, load_config
from autodev.core.models import Agent, AgentStatus, Base, Event, Task, TaskStatus

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

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Boot the system: DB → agents → API + worker (parallel)."""
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

    async def get_next_task(self) -> Task | None:
        """Return the highest-priority queued task, or None."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(Task)
                .where(Task.status == TaskStatus.QUEUED)
                .order_by(Task.priority, Task.created_at)
                .limit(1)
            )
            task = result.scalar_one_or_none()
            if task is not None:
                # Detach from session before returning
                await session.refresh(task)
            return task

    # ------------------------------------------------------------------
    # Task processing
    # ------------------------------------------------------------------

    async def process_task(self, task: Task) -> None:
        """Process a single task end-to-end."""
        task_id = str(task.id)
        repo_name = task.repo or ""
        workdir = f"/tmp/autodev-{task_id}"

        logger.info("Processing task %s: %s (repo=%s)", task_id, task.title, repo_name)

        # 1. Mark in_progress + assign developer agent
        await self._update_task_status(task_id, TaskStatus.IN_PROGRESS)
        await self._update_agent_status("developer", AgentStatus.WORKING, task_id)

        try:
            # 2. Clone repo (develop branch if it exists, else default)
            if repo_name:
                clone_url = f"https://x-access-token:{self.github_token}@github.com/zinchenkomig/{repo_name}.git" if self.github_token else f"https://github.com/zinchenkomig/{repo_name}.git"
                await self._run_shell(
                    f"git clone -b develop {clone_url} {workdir} "
                    f"|| git clone {clone_url} {workdir}",
                    timeout=120,
                )
            else:
                Path(workdir).mkdir(parents=True, exist_ok=True)

            # 3. Create feature branch
            branch = f"autodev-{task_id}"
            if repo_name:
                await self._run_shell(
                    f"git -C {workdir} checkout -b {branch}", timeout=30
                )

            # 4. Build instructions (task description + CLAUDE.md context)
            instructions = task.description or task.title
            claude_md = Path(workdir) / "CLAUDE.md"
            if claude_md.exists():
                context = claude_md.read_text(encoding="utf-8", errors="replace")
                instructions = f"{instructions}\n\n--- CLAUDE.md ---\n{context}"

            # 5. Run Claude Code
            from autodev.core.runner import ClaudeCodeRunner

            runner = ClaudeCodeRunner(model="claude-sonnet-4-20250514", timeout=600)
            logger.info("Running ClaudeCodeRunner for task %s", task_id)
            result = await runner.run(
                instructions, context={"workdir": workdir, "task_id": task_id}
            )
            logger.info(
                "ClaudeCodeRunner finished: status=%s duration=%.1fs",
                result.status,
                result.duration_seconds,
            )

            pr_number: int | None = None

            if result.status == "success" and repo_name:
                # 6. Commit & push
                commit_msg = f"feat: {task.title[:72]} [autodev-{task_id[:8]}]"
                await self._run_shell(
                    f"git -C {workdir} add -A && "
                    f'git -C {workdir} diff --cached --quiet || '
                    f'git -C {workdir} commit -m "{commit_msg}" && '
                    f"git -C {workdir} push -u origin {branch}",
                    timeout=60,
                )

                # 7. Create PR via GitHub
                pr_number = await self._create_pr(
                    repo=repo_name,
                    branch=branch,
                    title=task.title,
                    body=f"Automated PR for task {task_id}\n\n{task.description or ''}",
                )

            # 8. Update task status
            final_status = TaskStatus.DONE if result.status == "success" else TaskStatus.FAILED
            await self._update_task_status(task_id, final_status, pr_number=pr_number)

            # 9. Emit events
            await self._emit_event("task.completed", {"task_id": task_id, "status": final_status})
            if pr_number:
                await self._emit_event(
                    "pr.created",
                    {"task_id": task_id, "pr_number": pr_number, "repo": repo_name},
                )

            logger.info("Task %s finished: %s (pr=%s)", task_id, final_status, pr_number)

        except Exception as exc:
            logger.exception("Task %s failed with exception", task_id)
            await self._update_task_status(task_id, TaskStatus.FAILED)
            await self._emit_event("task.failed", {"task_id": task_id, "error": str(exc)})

        finally:
            # 10. Reset agent status
            await self._update_agent_status("developer", AgentStatus.IDLE, None)

            # 11. Cleanup workdir
            if Path(workdir).exists():
                shutil.rmtree(workdir, ignore_errors=True)
                logger.debug("Cleaned up %s", workdir)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        pr_number: int | None = None,
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

    async def _emit_event(self, event_type: str, payload: dict) -> None:
        async with self._session_factory() as session:
            event = Event(type=event_type, payload=payload, source="orchestrator")
            session.add(event)
            await session.commit()
            logger.info("Event emitted: %s %s", event_type, payload)

    async def _run_shell(self, cmd: str, timeout: int = 60) -> str:
        """Run a shell command, raising on failure."""
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
        if proc.returncode != 0:
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

if __name__ == "__main__":
    orchestrator = Orchestrator()
    asyncio.run(orchestrator.start())
