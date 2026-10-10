# Architecture

## Processes

```
            phone
              │  dashboard (Next.js)          Telegram
              ▼                                  │ webhook
┌──────────────────────────┐                     ▼
│ API  (AUTODEV_ROLE=api)  │◄──────────── /api/webhooks/telegram
│ FastAPI, k8s             │
└────────────┬─────────────┘
             │ Postgres (tasks, projects, logs, releases)
┌────────────┴──────────────────────────────────────────────┐
│ Worker (AUTODEV_ROLE=worker), host systemd, full rights    │
│                                                            │
│  developer-1..N  ── claim (SKIP LOCKED) ── develop()       │
│                       triage → checkout → Claude → push/PR │
│  delivery        ── every 2×poll: CI → merge → stage → ✅  │
│                     + pending releases (stage→main merge)  │
└────────────────────────────────────────────────────────────┘
             │ GitHub REST (polling)       │ Claude Agent SDK
```

## Code map

| path | what |
|---|---|
| `autodev/main.py` | entry point: migrations, seeding projects, start API and/or worker |
| `autodev/core/claude.py` | `ClaudeRunner`: one SDK session, log streaming, structured result, rate limits, host guard |
| `autodev/core/models.py` | `Project`, `Task` (statuses), `Release`, logs, transitions |
| `autodev/core/config.py` | env `Settings`, `autodev.yaml` schema |
| `autodev/worker/loop.py` | slots, claiming, recovery after restart |
| `autodev/worker/triage.py` | multi-repo projects: choose repo / split into dependent tasks |
| `autodev/worker/developer.py` | one development round: checkout → agent → commit → push → PR |
| `autodev/worker/workspace.py` | per-task clone at `$AUTODEV_WORKDIR/tasks/<task id>` |
| `autodev/worker/delivery.py` | CI/merge/stage verification, fix rounds, release merging |
| `autodev/release.py` | start a release: stage→prod PRs per repo |
| `autodev/notify.py` | Telegram notifications |
| `autodev/api/routes/` | REST API (`projects`, `tasks`, `releases`, `agents`, …) |

## A task's life

1. **Created** from the dashboard, Telegram or the CLI. A multi-repo project may leave
   `repo` empty.
2. **Claimed** by a free slot. The slot picks the highest priority first, then the oldest. A task is
   skipped while its project already runs `max_parallel` tasks or while a dependency is not merged yet.
3. **Triage** (only when `repo` is empty): a short Claude call picks the repo. If the change spans
   repos it creates follow-up tasks, each depending on the previous one (API before UI).
4. **Develop**:
   - fresh partial clone; new branch `autodev/<n>-<slug>` from the base branch
     (or the existing branch for fix rounds)
   - repo `setup` script, e.g. OpenAPI client generation
   - one Claude session with the system rules from `worker/prompts.py`
   - the session ends with `{status: done|blocked, summary}`
   - leftovers are committed; then push and open a PR to the base branch. The summary becomes the PR body.
5. **CI**: the delivery loop polls check runs on the PR head.
   - red checks → back to `queued` with `metadata.fix = {kind: "ci"}`. The next round resumes the
     same Claude session.
   - merge conflict → `kind: "conflict"`. The worker merges the base branch first and Claude
     resolves only if conflicts remain.
   - green checks, or no checks after a grace period → squash-merge.
   - `AUTODEV_MAX_FIX_ATTEMPTS` caps the fix rounds.
6. **Deploying**: the change counts as on stage when either
   - the repo's `version_url` reports a commit that contains the merge commit, or
   - (without `version_url`) every push workflow for that commit, or a newer commit containing it,
     succeeded on the base branch.
7. **On stage**: Telegram notification with the stage link and the summary.
8. **Release**: `POST /api/projects/{id}/release`.
   - opens stage→prod PRs for every repo that has changes
   - the delivery loop merges them with a merge commit once their checks pass. A squash here would
     make the next stage→main PR conflict.
   - then the tasks become `released`.

## Owner actions

- **Cancel**: allowed in queued, in_progress or ci. A running Claude session is stopped within ~5 s.
- **Retry**: allowed in failed or cancelled. The previous error is passed to the agent.
- **Feedback**:
  - before merge — another round on the same PR
  - after merge — a follow-up task that depends on the original
- **Pause everything**: toggle the `developer` agent off in the dashboard.

## Subscription limits

Claude reports a rejected rate limit (`rate_limit_event`), or the result text says the limit was hit.
In that case the task goes back to `queued` and every slot pauses until the reset time.
