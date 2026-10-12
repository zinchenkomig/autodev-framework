"""The owner's manual check of a task on stage: the test-plan checklist and the "verified" mark.

Both live in task metadata: ``plan_checked`` (indices of ticked ``test_plan``
steps) and ``verified_at`` (ISO time the owner accepted the change). A new
test plan resets them.
"""

from __future__ import annotations

from datetime import UTC, datetime

from autodev.core.models import MERGED_STATUSES, Task


class ReviewError(ValueError):
    pass


def plan_checked(task: Task) -> list[int]:
    plan = (task.metadata_ or {}).get("test_plan") or []
    checked = (task.metadata_ or {}).get("plan_checked") or []
    return sorted(i for i in set(checked) if isinstance(i, int) and 0 <= i < len(plan))


def verified_at(task: Task) -> str | None:
    return (task.metadata_ or {}).get("verified_at")


def check_step(task: Task, step: int, done: bool) -> None:
    """Tick or untick one step. Ticking the last one marks the task verified; unticking takes the mark back."""
    _require_on_stage(task)
    plan = (task.metadata_ or {}).get("test_plan") or []
    if not 0 <= step < len(plan):
        raise ReviewError(f"No step {step + 1} in the test plan")
    checked = set(plan_checked(task))
    if done:
        checked.add(step)
    else:
        checked.discard(step)
    metadata = {**(task.metadata_ or {}), "plan_checked": sorted(checked)}
    if done and len(checked) == len(plan):
        metadata.setdefault("verified_at", _now())
    elif not done:
        metadata.pop("verified_at", None)
    task.metadata_ = metadata


def set_verified(task: Task, verified: bool) -> None:
    _require_on_stage(task)
    metadata = dict(task.metadata_ or {})
    if verified:
        metadata.setdefault("verified_at", _now())
    else:
        metadata.pop("verified_at", None)
    task.metadata_ = metadata


def reset(metadata: dict) -> dict:
    """Metadata without the owner's check — for when the change or its plan is new."""
    return {k: v for k, v in metadata.items() if k not in ("plan_checked", "verified_at")}


def _require_on_stage(task: Task) -> None:
    if task.status not in MERGED_STATUSES:
        raise ReviewError(f"Nothing to check on stage while the task is {task.status}")


def _now() -> str:
    return datetime.now(UTC).isoformat()
