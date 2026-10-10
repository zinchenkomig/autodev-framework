"""Model helpers."""

from autodev.core.models import MERGED_STATUSES, TERMINAL_STATUSES, TaskStatus
from tests.conftest import make_project


def test_repo_lookup_by_name_bare_name_and_role() -> None:
    p = make_project(repos=[{"name": "acme/api", "role": "backend"}, {"name": "acme/web", "role": "frontend"}])
    assert p.repo("acme/api")["role"] == "backend"
    assert p.repo("web")["name"] == "acme/web"
    assert p.repo("frontend")["name"] == "acme/web"
    assert p.repo("nope") is None


def test_repo_default_only_for_single_repo_projects() -> None:
    assert make_project().repo(None)["name"] == "acme/shop"
    two = make_project(repos=[{"name": "acme/a"}, {"name": "acme/b"}])
    assert two.repo(None) is None


def test_status_groups() -> None:
    assert TaskStatus.ON_STAGE in MERGED_STATUSES
    assert TaskStatus.CI not in MERGED_STATUSES
    assert TERMINAL_STATUSES == {TaskStatus.RELEASED, TaskStatus.FAILED, TaskStatus.CANCELLED}
