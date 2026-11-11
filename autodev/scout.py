"""The scout: walks a project on its own and finds what is worth changing.

Every other agent starts from a task the owner wrote. The scout writes tasks: it reads
the stage branch, opens stage in a phone-sized browser and holds what it sees against
the project's idea (``Project.idea``): what is broken, what the idea still lacks, what
is superfluous, what in the code a person can't read. It returns a few findings, each
with evidence (:mod:`autodev.worker.scout`). What happens to them is the project's mode:

- ``propose``: they wait in status ``proposed`` until the owner takes or rejects them;
- ``auto``: they go straight to the queue, then down the usual pipeline (PM, developer,
  stage). ``off`` runs only when asked (the dashboard's button), and proposes.

The brake is ``Project.stage_limit``: everything already on stage, on its way there or
waiting for a decision counts (follow-ups too), and the scout never brings the project
over the limit. Releasing to prod is the owner's, so an unattended project fills up to
the limit and stops. The limit only holds the scout back, never the owner's own tasks.

The last run is kept in ``Project.scout_run``: {"state", "at", "found", "summary", ...}.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from autodev.core.models import OPEN_STATUSES, Project, Task, TaskStatus

OFF, PROPOSE, AUTO = "off", "propose", "auto"

#: Who created a task, and its metadata: {"kind", "evidence", "rejected": the owner's reason}.
AUTHOR = KEY = "scout"
#: What a finding is: something broken, awkward, missing from the idea, superfluous, unguarded, hard to read.
KINDS = ("bug", "ux", "feature", "simplify", "tests", "debt")

#: ``scout_run["state"]``: the owner pressed the button / a session runs / it ended.
REQUESTED, RUNNING, DONE, FAILED = "requested", "running", "done", "failed"

#: Statuses taking up room under the stage limit.
COUNTED = frozenset({TaskStatus.ON_STAGE, TaskStatus.PROPOSED, *OPEN_STATUSES})


def now() -> str:
    return datetime.now(UTC).isoformat()


def last_run(project: Project) -> dict:
    return project.scout_run if isinstance(project.scout_run, dict) else {}


def active(project: Project) -> bool:
    return last_run(project).get("state") in (REQUESTED, RUNNING)


def request(project: Project) -> None:
    project.scout_run = {"state": REQUESTED, "at": now()}


def rejected(task: Task) -> str | None:
    """The owner's reason for rejecting the proposal ("" without one), None if not rejected."""
    if task.status != TaskStatus.CANCELLED:
        return None
    return ((task.metadata_ or {}).get(KEY) or {}).get("rejected")


async def stage_load(session: AsyncSession, project_id: str) -> int:
    """Tasks under the limit. The scout's failed ones too: nobody looks, it must not keep producing them."""
    return await session.scalar(
        select(func.count())
        .select_from(Task)
        .where(
            Task.project_id == project_id,
            or_(
                Task.status.in_(COUNTED),
                and_(Task.status == TaskStatus.FAILED, Task.created_by == AUTHOR),
            ),
        )
    )


async def room(session: AsyncSession, project: Project) -> int:
    """How many more tasks the stage limit leaves."""
    return max(0, project.stage_limit - await stage_load(session, project.id))
