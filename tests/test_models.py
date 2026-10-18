"""Model helpers."""

from autodev.core.models import MERGED_STATUSES, TERMINAL_STATUSES, TaskStatus
from tests.conftest import make_project


def test_project_repo() -> None:
    p = make_project()
    assert p.repo()["name"] == p.repo("acme/shop")["name"] == p.repo("shop")["name"] == "acme/shop"
    assert p.repo("acme/other") is None


def test_status_groups() -> None:
    assert TaskStatus.ON_STAGE in MERGED_STATUSES
    assert TaskStatus.CI not in MERGED_STATUSES
    assert TERMINAL_STATUSES == {TaskStatus.RELEASED, TaskStatus.FAILED, TaskStatus.CANCELLED}
