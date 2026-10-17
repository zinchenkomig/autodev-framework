"""Merging a follow-up's proposed plan into its main task's plan."""

from __future__ import annotations

from autodev.review import merge_plan


def test_proposal_wins_when_plan_unchanged() -> None:
    assert merge_plan(["a", "b"], ["a", "b"], ["a", "b2", "c"]) == ["a", "b2", "c"]
    assert merge_plan([], [], ["a"]) == ["a"]


def test_concurrent_follow_up_only_adds_its_new_steps() -> None:
    # Another follow-up landed after this one's agent saw ["a", "b"].
    assert merge_plan(["a", "b", "x"], ["a", "b"], ["a", "b", "c"]) == ["a", "b", "x", "c"]


def test_empty_proposal_keeps_plan() -> None:
    assert merge_plan(["a"], ["a"], []) == ["a"]
