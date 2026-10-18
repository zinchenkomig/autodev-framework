# Deployment (server 188, k3s)

| part | where | how it updates |
|---|---|---|
| API + dashboard + Postgres | k3s, namespace `app-autodev`, ArgoCD app `app-autodev` (manifests in `hetzner-gitops/autodev`) | `autodev-update.timer` runs `kubectl rollout restart` after the Deploy workflow has built `:main` images |
| worker | host, `autodev-worker.service`, root, checkout at `/opt/autodev` | the same timer: raises `/run/autodev/drain` (worker stops taking new tasks), waits until no task is in progress, then `git reset` to main, `uv sync`, restart. `systemctl stop` also waits for running Claude sessions (up to 50 min) |

The worker runs on the host with full rights so the agent can install toolchains, run
tests, docker and browsers. `core/claude.py` has a deny-list guard for commands that would
hurt the node or other workloads.

## Files on the host

- `/etc/autodev/worker.env` (0600) — worker environment:
  ```
  AUTODEV_ROLE=worker
  DATABASE_URL=postgresql+asyncpg://autodev:<db password>@10.43.200.10:5432/autodev
  GITHUB_TOKEN=<token with repo + workflow>
  AUTODEV_WORKDIR=/var/lib/autodev/work
  AUTODEV_PUBLIC_URL=https://autodev.zinchenkomig.com
  AUTODEV_WORKER_SLOTS=2
  ```
- `/etc/autodev/secrets.env` (0600) — the generated DB password and the dashboard login.
- Claude Code auth: root's `~/.claude` login, or `CLAUDE_CODE_OAUTH_TOKEN` in `worker.env`.

## First install

```bash
git clone https://github.com/zinchenkomig/autodev-framework /opt/autodev
cd /opt/autodev && uv sync --frozen --no-dev --extra qa && uv run --no-sync playwright install --with-deps chromium
cp deploy/host/autodev-*.service deploy/host/autodev-update.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now autodev-worker autodev-update.timer
```

## Operations

```bash
journalctl -u autodev-worker -f            # what the agents are doing
journalctl -u autodev-update               # rollouts
systemctl stop autodev-worker              # emergency stop (tasks are requeued on start)
kubectl -n app-autodev logs deploy/autodev-api -f
```

Pause all development without stopping anything: switch the `developer` agent off in the
dashboard, or `UPDATE agents SET enabled=false WHERE id='developer'`.

## Telegram

1. In the dashboard: Settings → Telegram → paste the bot token and your chat id.
2. Press "Set webhook". It registers `https://autodev.zinchenkomig.com/api/webhooks/telegram`
   with a secret token. That path is exempt from the login (as is `/api/auth/*`, the login itself).

## Login

Traefik's `forward-auth` middleware asks `/api/auth/check` about every request. It lets
through the `autodev_session` cookie (set by the login form at `/api/auth/login`, lives a
year, so the home-screen app stays signed in) or a basic-auth header (curl, scripts).
Users and passwords are the htpasswd secret `autodev-basic-auth`, mounted into the API as
`AUTODEV_HTPASSWD`; changing it signs every session out.
