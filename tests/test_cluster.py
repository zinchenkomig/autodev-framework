"""Deploy diagnosis from the cluster (kubectl output parsing)."""

from __future__ import annotations

import json

import pytest

from autodev.worker import cluster


@pytest.fixture
def kubectl(monkeypatch):
    responses: dict[str, str] = {}
    calls: list[tuple] = []

    async def fake(*args):
        calls.append(args)
        for key, value in responses.items():
            if key in " ".join(args):
                if isinstance(value, Exception):
                    raise value
                return value
        raise RuntimeError(f"unexpected kubectl {args}")

    monkeypatch.setattr(cluster, "kubectl", fake)
    fake.responses, fake.calls = responses, calls
    return fake


def app(phase=None, message="", hook_failed=False, revisions=("sha1", "gitops1")):
    op = {}
    if phase:
        resources = [{"kind": "Job", "name": "migrate", "hookPhase": "Failed"}] if hook_failed else []
        op = {"phase": phase, "message": message, "syncResult": {"revisions": list(revisions), "resources": resources}}
    return json.dumps({"status": {"operationState": op}})


def pods(*statuses):
    items = [
        {
            "metadata": {"name": f"app-{i}"},
            "spec": {"containers": [{"image": "ghcr.io/org/notes:sha2"}]},
            "status": {"containerStatuses": [s]},
        }
        for i, s in enumerate(statuses)
    ]
    return json.dumps({"items": items})


def crashing(restarts=5):
    return {"restartCount": restarts, "state": {"waiting": {"reason": "CrashLoopBackOff"}}}


async def test_failed_migration_reports_job_logs(kubectl) -> None:
    kubectl.responses["get application p-notes-stage"] = app("Failed", "job migrate failed", hook_failed=True)
    kubectl.responses["logs job/migrate"] = "alembic: column exists\n"
    failure = await cluster.diagnose("Org/Notes")
    assert failure.sha == "sha1"
    assert "job migrate failed" in failure.text and "alembic: column exists" in failure.text


async def test_crash_looping_app(kubectl) -> None:
    kubectl.responses["get application"] = app("Succeeded")
    kubectl.responses["get pods"] = pods(crashing())
    kubectl.responses["logs pod/app-0"] = "Traceback: boom"
    failure = await cluster.diagnose("org/notes")
    assert failure.sha == "sha2" and "Traceback: boom" in failure.text
    assert ("-n", "p-notes-stage", "logs", "pod/app-0", "--tail=80", "--previous") in kubectl.calls


@pytest.mark.parametrize(
    "pod_status",
    [
        crashing(restarts=1),  # just started crashing: give it a chance
        {"restartCount": 0, "state": {"waiting": {"reason": "ImagePullBackOff"}}},  # image still building
        {"restartCount": 0, "state": {"running": {}}},
    ],
)
async def test_nothing_definite(kubectl, pod_status) -> None:
    kubectl.responses["get application"] = app("Running")
    kubectl.responses["get pods"] = pods(pod_status)
    assert await cluster.diagnose("org/notes") is None


async def test_unreachable_cluster_is_not_a_failure(kubectl) -> None:
    kubectl.responses["get application"] = RuntimeError("NotFound")
    assert await cluster.diagnose("org/notes") is None
