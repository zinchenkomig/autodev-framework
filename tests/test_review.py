"""The owner's check: merging a follow-up's plan, and ticks carried across versions."""

from __future__ import annotations

from autodev.core.models import Task, TaskStatus
from autodev.review import (
    adopt_child_plan,
    check_step,
    merge_plan,
    new_version,
    plan_checked,
    plan_earlier,
    verified_at,
)


def test_proposal_wins_when_plan_unchanged() -> None:
    assert merge_plan(["a", "b"], ["a", "b"], ["a", "b2", "c"]) == ["a", "b2", "c"]
    assert merge_plan([], [], ["a"]) == ["a"]


def test_concurrent_follow_up_only_adds_its_new_steps() -> None:
    # Another follow-up landed after this one's agent saw ["a", "b"].
    assert merge_plan(["a", "b", "x"], ["a", "b"], ["a", "b", "c"]) == ["a", "b", "x", "c"]


def test_empty_proposal_keeps_plan() -> None:
    assert merge_plan(["a"], ["a"], []) == ["a"]


def _task(**metadata) -> Task:
    return Task(title="t", status=TaskStatus.ON_STAGE, metadata_=metadata)


def test_new_plan_keeps_ticks_of_unchanged_steps_as_earlier() -> None:
    old = {"test_plan": ["a", "b", "c  d", "e"], "plan_checked": [0, 2], "plan_earlier": [3], "verified_at": "x"}
    got = new_version(old, ["new", "c d", "b", "a", "e"])
    # Matched by text (whitespace aside), wherever the step moved; unticked "b" stays unticked.
    assert got == {"test_plan": ["new", "c d", "b", "a", "e"], "plan_earlier": [1, 3, 4]}


def test_same_text_twice_carries_as_many_ticks_as_there_were() -> None:
    got = new_version({"test_plan": ["a", "a", "b"], "plan_checked": [0]}, ["a", "a"])
    assert got["plan_earlier"] == [0]


def test_new_code_with_the_same_plan_makes_every_tick_earlier() -> None:
    got = new_version({"test_plan": ["a", "b"], "plan_checked": [0, 1], "verified_at": "x"})
    assert got == {"test_plan": ["a", "b"], "plan_earlier": [0, 1]}
    assert new_version({"test_plan": ["a"]}) == {"test_plan": ["a"]}


def test_earlier_ticks_count_only_after_checking_again() -> None:
    task = _task(test_plan=["a", "b"], plan_checked=[], plan_earlier=[0, 1])
    check_step(task, 0, True)
    assert plan_checked(task) == [0] and plan_earlier(task) == [1] and verified_at(task) is None
    check_step(task, 1, False)  # looked at it: broken now
    assert plan_earlier(task) == [] and "plan_earlier" not in task.metadata_
    check_step(task, 1, True)
    assert verified_at(task)


def test_follow_up_landing_carries_ticks_into_the_merged_plan() -> None:
    root = _task(test_plan=["a", "b"], plan_checked=[0, 1], verified_at="x")
    child = Task(title="c", metadata_={"root_plan": {"base": ["a", "b"], "plan": ["a", "b2", "c"]}})
    adopt_child_plan(root, child)
    assert root.metadata_ == {"test_plan": ["a", "b2", "c"], "plan_earlier": [0]}

    # No new plan from the follow-up: the code is new all the same.
    root = _task(test_plan=["a"], plan_checked=[0])
    adopt_child_plan(root, Task(title="c", metadata_={}))
    assert root.metadata_ == {"test_plan": ["a"], "plan_earlier": [0]}
