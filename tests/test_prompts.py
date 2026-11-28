"""The agents' rules: what they share."""

from __future__ import annotations

from autodev.worker import prompts


def test_everyone_who_shapes_the_interface_works_by_the_same_rules() -> None:
    for rules in (
        prompts.PM_SYSTEM,
        prompts.SYSTEM,
        prompts.REVIEW_SYSTEM,
        prompts.ACCEPT_SYSTEM,
        prompts.SCOUT_SYSTEM,
    ):
        assert prompts.UI_RULES in rules
    for rules in (prompts.PLANNER_SYSTEM, prompts.CHAT_SYSTEM):  # they write no interface
        assert prompts.UI_RULES not in rules
