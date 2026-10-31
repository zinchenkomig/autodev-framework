#!/bin/bash
# Roll out a new main commit once its Deploy workflow (images) has succeeded.
#
# A running Claude session is never cut off: when an update is ready the
# script creates $DRAIN, the worker stops taking new tasks, and the restart
# happens on a later run once no task is in progress. The worker resumes
# taking tasks as soon as the flag is gone.
set -euo pipefail

REPO=zinchenkomig/autodev-framework
DIR=/opt/autodev
NS=app-autodev
DRAIN=${AUTODEV_DRAIN_FILE:-/run/autodev/drain}
# Wait this long after raising the flag, so a slot that was just claiming a task (or a chat)
# has registered it before we count running tasks.
SETTLE=60
cd "$DIR"

# A failed update must not leave the worker paused; the next run starts over.
trap 'rc=$?; [ $rc -ne 0 ] && rm -f "$DRAIN"; exit $rc' EXIT

git fetch -q origin main
current=$(git rev-parse HEAD)
target=$(git rev-parse origin/main)
if [ "$current" = "$target" ]; then
  rm -f "$DRAIN"
  exit 0
fi

conclusion=$(gh run list -R "$REPO" --workflow deploy.yml --commit "$target" --json conclusion -q '.[0].conclusion' || true)
if [ "$conclusion" != "success" ]; then
  echo "main at ${target:0:7}: Deploy workflow is '${conclusion:-not started}', waiting"
  exit 0
fi

if [ ! -e "$DRAIN" ]; then
  mkdir -p "$(dirname "$DRAIN")"
  touch "$DRAIN"
  echo "update ${target:0:7} ready — worker stops taking new tasks"
fi
age=$(( $(date +%s) - $(stat -c %Y "$DRAIN") ))
[ "$age" -lt "$SETTLE" ] && sleep $(( SETTLE - age ))

busy=$(uv run --no-sync python - <<'PY'
import asyncio
from sqlalchemy import func, select
from autodev.api.database import SessionLocal
from autodev.core.models import Agent, AgentStatus, Chat, ChatState, Task, TaskStatus

async def main():
    async with SessionLocal() as s:
        tasks = await s.scalar(select(func.count()).select_from(Task).where(Task.status == TaskStatus.IN_PROGRESS))
        # The planner rebuilds a test plan without moving the task to in_progress.
        planner = await s.scalar(
            select(func.count()).select_from(Agent).where(Agent.id == "planner", Agent.status == AgentStatus.WORKING)
        )
        chats = await s.scalar(select(func.count()).select_from(Chat).where(Chat.state == ChatState.ANSWERING))
        print(tasks + planner + chats)

asyncio.run(main())
PY
)
if [ "${busy:-0}" != "0" ]; then
  echo "update ${target:0:7} waits for $busy running task(s) and chat answer(s)"
  exit 0
fi

echo "updating ${current:0:7} → ${target:0:7}"
git reset -q --hard "$target"
uv sync -q --frozen --no-dev --extra qa
uv run --no-sync playwright install chromium >/dev/null
cp deploy/host/autodev-worker.service deploy/host/autodev-update.service deploy/host/autodev-update.timer /etc/systemd/system/
systemctl daemon-reload
kubectl -n "$NS" rollout restart deploy/autodev-api deploy/autodev-dashboard
systemctl restart autodev-worker
rm -f "$DRAIN"
echo "done"
