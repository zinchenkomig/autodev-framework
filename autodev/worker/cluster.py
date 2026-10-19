"""Why a deploy of a projects-org repo didn't reach stage, asked from the cluster.

The worker runs on the k3s host, so ``kubectl`` reaches the cluster directly.
Repos in the projects organization are deployed by ArgoCD into ``p-<repo>-<env>``
(hetzner-gitops: argocd/appset-projects.yaml); a failed sync (usually the
migration Job) or a crash-looping app pod there is a definite failure, worth a
fix task with the logs instead of waiting for the deploy timeout.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from autodev.core import shell

logger = logging.getLogger(__name__)

FAILED_PHASES = {"Failed", "Error"}
CRASH_RESTARTS = 3  # restarts of a crash-looping container before we call it broken
LOG_LINES = 80


@dataclass
class DeployFailure:
    sha: str  # commit of the failing revision
    text: str  # what failed, with logs


def names(repo: str, env: str = "stage") -> tuple[str, str]:
    """(ArgoCD application, namespace) of *repo*'s environment."""
    name = f"p-{repo.split('/', 1)[1].lower()}-{env}"
    return name, name


async def kubectl(*args: str) -> str:
    return await shell.run("kubectl", *args, timeout=30)


async def diagnose(repo: str, env: str = "stage") -> DeployFailure | None:
    """A definite failure of the latest deploy, or None (fine, still going, or unknown)."""
    app, ns = names(repo, env)
    try:
        return await _failed_sync(app, ns) or await _crashing_app(ns)
    except Exception as exc:  # no kubectl, no app yet, API hiccup: nothing to report
        logger.debug("diagnose %s: %s", app, exc)
        return None


async def _failed_sync(app: str, ns: str) -> DeployFailure | None:
    status = json.loads(await kubectl("-n", "argocd", "get", "application", app, "-o", "json")).get("status", {})
    op = status.get("operationState") or {}
    if op.get("phase") not in FAILED_PHASES:
        return None
    revisions = (op.get("syncResult") or {}).get("revisions") or (op.get("operation") or {}).get("sync", {}).get(
        "revisions"
    )
    if not revisions:
        return None
    text = f"ArgoCD не смог выкатить {app}: {op.get('message', '').strip()}"
    resources = (op.get("syncResult") or {}).get("resources") or []
    for r in resources:
        if r.get("status") not in (None, "Synced") and r.get("message"):
            text += f"\n- {r.get('kind')}/{r.get('name')}: {r['message']}"
    failed_hooks = [r for r in resources if r.get("hookPhase") in FAILED_PHASES]
    if any(r.get("kind") == "Job" and r.get("name") == "migrate" for r in failed_hooks):
        logs = await _logs(ns, "job/migrate")
        text += "\n\nМиграции (`migrate.command`) упали. Лог:\n" + logs
    return DeployFailure(sha=revisions[0], text=text)


async def _crashing_app(ns: str) -> DeployFailure | None:
    pods = json.loads(await kubectl("-n", ns, "get", "pods", "-l", "app.kubernetes.io/name=app", "-o", "json"))
    for pod in pods.get("items", []):
        image = pod["spec"]["containers"][0]["image"]
        for status in pod.get("status", {}).get("containerStatuses") or []:
            waiting = (status.get("state") or {}).get("waiting") or {}
            if waiting.get("reason") == "CrashLoopBackOff" and status.get("restartCount", 0) >= CRASH_RESTARTS:
                name = pod["metadata"]["name"]
                logs = await _logs(ns, f"pod/{name}", previous=True)
                text = (
                    f"Приложение падает после старта ({name}, {status['restartCount']} рестартов). "
                    f"Лог последнего запуска:\n{logs}"
                )
                return DeployFailure(sha=image.rsplit(":", 1)[-1], text=text)
    return None


async def _logs(ns: str, target: str, previous: bool = False) -> str:
    args = ["-n", ns, "logs", target, f"--tail={LOG_LINES}"]
    if previous:
        args.append("--previous")
    try:
        return (await kubectl(*args)).strip() or "(пусто)"
    except Exception as exc:
        return f"(лог недоступен: {exc})"
