"""The owner's manual check of a task on stage: the test-plan checklist and the "verified" mark.

Both live in task metadata: ``plan_checked`` (indices of ticked ``test_plan``
steps) and ``verified_at`` (ISO time the owner accepted the change).
``plan_refresh`` marks a requested rebuild of the plan.

A new version — a new plan, or a follow-up's change landing on stage — starts the
check over, but the owner's ticks aren't lost: a step whose text an earlier version
had ticked is listed in ``plan_earlier`` ("checked on the previous version"). It
doesn't count until the owner ticks it again, since the new code may have broken it.

The owner checks a main task as a whole: its follow-ups, parts and fixes have no
plan of their own. Their agent proposes the main task's updated plan
(``root_plan`` in the child's metadata), which replaces the main task's plan once
the child is on stage. The main task can't be marked verified while any of its
children is still on the way to stage.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autodev.core.models import MERGED_STATUSES, OPEN_STATUSES, Task

#: Longest plan kept for a main task (it grows with follow-ups).
MAX_PLAN = 20
#: Metadata key of a pending plan rebuild (``autodev.worker.planner``): ``{"requested_at": iso}``.
REFRESH = "plan_refresh"
#: Metadata key: indices of steps checked on an earlier version of the change or the plan.
EARLIER = "plan_earlier"


class ReviewError(ValueError):
    pass


def checked_with_main(task: Task) -> bool:
    """A follow-up/part: checked as part of its main task, by the main task's one plan."""
    return bool(task.parent_id)


def plan_checked(task: Task) -> list[int]:
    return _steps(task.metadata_ or {}, "plan_checked")


def plan_earlier(task: Task) -> list[int]:
    """Steps checked on an earlier version and not ticked again on this one."""
    checked = set(plan_checked(task))
    return [i for i in _steps(task.metadata_ or {}, EARLIER) if i not in checked]


def _steps(metadata: dict, key: str) -> list[int]:
    plan = metadata.get("test_plan") or []
    marked = metadata.get(key) or []
    return sorted(i for i in set(marked) if isinstance(i, int) and 0 <= i < len(plan))


def verified_at(task: Task) -> str | None:
    return (task.metadata_ or {}).get("verified_at")


def check_step(task: Task, step: int, done: bool, waiting: list[Task] = ()) -> None:
    """Tick or untick one step. Ticking the last one marks the task verified; unticking takes the mark back.

    While *waiting* (open children) is not empty the steps can be ticked, but the task isn't verified yet.
    """
    _require_on_stage(task)
    if checked_with_main(task):
        raise ReviewError("Проверяется в основной задаче")
    plan = (task.metadata_ or {}).get("test_plan") or []
    if not 0 <= step < len(plan):
        raise ReviewError(f"No step {step + 1} in the test plan")
    checked = set(plan_checked(task))
    if done:
        checked.add(step)
    else:
        checked.discard(step)
    # Either way the owner has looked at the step on this version: the earlier tick is settled.
    earlier = [i for i in plan_earlier(task) if i != step]
    metadata = {**(task.metadata_ or {}), "plan_checked": sorted(checked), EARLIER: earlier}
    if not earlier:
        metadata.pop(EARLIER)
    if done and len(checked) == len(plan) and not waiting:
        metadata.setdefault("verified_at", _now())
    elif not done:
        metadata.pop("verified_at", None)
    task.metadata_ = metadata


def set_verified(task: Task, verified: bool, waiting: list[Task] = ()) -> None:
    _require_on_stage(task)
    if checked_with_main(task):
        raise ReviewError("Проверяется в основной задаче")
    metadata = dict(task.metadata_ or {})
    if verified:
        if waiting:
            raise ReviewError(f"Ждёт доработок: {', '.join(f'#{t.ticket_number}' for t in waiting)}")
        metadata.setdefault("verified_at", _now())
    else:
        metadata.pop("verified_at", None)
    task.metadata_ = metadata


def request_refresh(task: Task) -> None:
    """Ask the planner to write the main task's plan again from the task, its follow-ups and stage."""
    if checked_with_main(task):
        raise ReviewError("План собирается в основной задаче")
    _require_on_stage(task)
    if REFRESH in (task.metadata_ or {}):
        raise ReviewError("План уже пересобирается")
    task.metadata_ = {**(task.metadata_ or {}), REFRESH: {"requested_at": _now()}}


def reset(metadata: dict) -> dict:
    """Metadata without the owner's check, earlier ticks included."""
    return {k: v for k, v in metadata.items() if k not in ("plan_checked", "verified_at", EARLIER)}


def new_version(metadata: dict, plan: list[str] | None = None) -> dict:
    """Metadata for a new version of the change and/or its plan (*plan*; None keeps the current one).

    The check starts over. Steps of the new plan whose text was ticked before (now or on an
    earlier version) are marked as checked on the previous version; matching is by text, so a
    step that moved keeps its mark and a reworded one loses it.
    """
    old = metadata.get("test_plan") or []
    plan = old if plan is None else plan
    ticked = set(_steps(metadata, "plan_checked")) | set(_steps(metadata, EARLIER))
    pool = Counter(_norm(old[i]) for i in ticked)
    earlier = []
    for i, step in enumerate(plan):
        if pool[_norm(step)] > 0:
            pool[_norm(step)] -= 1
            earlier.append(i)
    metadata = reset({**metadata, "test_plan": plan})
    if earlier:
        metadata[EARLIER] = earlier
    return metadata


def _norm(step: str) -> str:
    return " ".join(step.split())


def unverify(metadata: dict) -> dict:
    """Metadata without the "verified" mark (ticked steps stay)."""
    return {k: v for k, v in metadata.items() if k != "verified_at"}


def merge_plan(current: list[str], base: list[str], proposed: list[str]) -> list[str]:
    """The main task's plan after a child proposes *proposed*, written against *base*.

    If the plan hasn't changed since the child's agent saw it, the proposal wins as is;
    otherwise (another child landed meanwhile) keep the current plan and add the proposal's new steps.
    """
    if not proposed:
        return current
    if current == base or not current:
        return proposed[:MAX_PLAN]
    return (current + [s for s in proposed if s not in base and s not in current])[:MAX_PLAN]


def adopt_child_plan(root: Task, child: Task) -> None:
    """*child* reached stage: its change is part of what the owner checks on *root*, so the check starts over.

    The code on stage is new even when the plan stays, so every tick becomes an earlier one.
    """
    metadata = dict(root.metadata_ or {})
    plan = None
    proposal = (child.metadata_ or {}).get("root_plan")
    if isinstance(proposal, dict):
        plan = merge_plan(metadata.get("test_plan") or [], proposal.get("base") or [], proposal.get("plan") or [])
    root.metadata_ = new_version(metadata, plan)


async def waiting_children(session: AsyncSession, root_ids: set[uuid.UUID]) -> dict[uuid.UUID, list[Task]]:
    """Open children (not on stage yet) of each main task in *root_ids*."""
    if not root_ids:
        return {}
    rows = await session.execute(
        select(Task).where(Task.parent_id.in_(root_ids), Task.status.in_(OPEN_STATUSES)).order_by(Task.ticket_number)
    )
    waiting: dict[uuid.UUID, list[Task]] = defaultdict(list)
    for child in rows.scalars():
        waiting[child.parent_id].append(child)
    return waiting


def _require_on_stage(task: Task) -> None:
    if task.status not in MERGED_STATUSES:
        raise ReviewError(f"Nothing to check on stage while the task is {task.status}")


def _now() -> str:
    return datetime.now(UTC).isoformat()
