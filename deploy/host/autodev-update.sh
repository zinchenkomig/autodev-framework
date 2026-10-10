#!/bin/bash
# Roll out a new main commit once its Deploy workflow (images) has succeeded.
# Restarts the worker only while no developer slot is busy, so a running
# Claude session is never cut off by an update.
set -euo pipefail

REPO=zinchenkomig/autodev-framework
DIR=/opt/autodev
NS=app-autodev
cd "$DIR"

git fetch -q origin main
current=$(git rev-parse HEAD)
target=$(git rev-parse origin/main)
[ "$current" = "$target" ] && exit 0

conclusion=$(gh run list -R "$REPO" --workflow deploy.yml --commit "$target" --json conclusion -q '.[0].conclusion' || true)
if [ "$conclusion" != "success" ]; then
  echo "main at ${target:0:7}: Deploy workflow is '${conclusion:-not started}', waiting"
  exit 0
fi

busy=$(uv run --no-sync python - <<'PY'
import asyncio
from sqlalchemy import func, select
from autodev.api.database import SessionLocal
from autodev.core.models import Agent

async def main():
    async with SessionLocal() as s:
        print(await s.scalar(select(func.count()).select_from(Agent).where(Agent.status == "working")))

asyncio.run(main())
PY
)
if [ "${busy:-0}" != "0" ]; then
  echo "update ${target:0:7} ready, but $busy slot(s) busy — retrying later"
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
echo "done"
