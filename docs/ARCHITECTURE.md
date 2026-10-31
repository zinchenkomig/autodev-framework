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
│                       checkout → Claude → push/PR          │
│  delivery        ── every 2×poll: CI → merge → stage → ✅  │
│                     + pending releases (stage→main merge)  │
│  planner         ── requested test-plan rebuilds           │
│  chat-1..N       ── answer the owner in chats (read-only)  │
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
| `autodev/worker/developer.py` | one development round: checkout → agent → commit → push → PR |
| `autodev/worker/workspace.py` | per-task clone at `$AUTODEV_WORKDIR/tasks/<task id>` |
| `autodev/chats.py` | chat subjects: the agent's context and the actions it may propose |
| `autodev/worker/chat.py` | chat slots: one read-only Claude turn per owner message |
| `autodev/worker/planner.py` | rebuild a main task's test plan from the task, its follow-ups and stage |
| `autodev/worker/delivery.py` | CI/merge/stage verification, fix rounds, release merging |
| `autodev/release.py` | start a release: the stage→prod PR |
| `autodev/notify.py` | Telegram notifications |
| `autodev/api/routes/` | REST API (`projects`, `tasks`, `releases`, `agents`, …) |

## A task's life

1. **Created** from the dashboard, Telegram or the CLI. A project has exactly one repo; keep
   several apps (backend + frontend) in a monorepo so one task changes them together, in one PR.
2. **Claimed** by a free slot. The slot picks the highest priority first, then the oldest. A task is
   skipped while its project already runs `max_parallel` tasks or while a dependency is not merged yet.
3. **Develop**:
   - fresh partial clone; new branch `autodev/<n>-<slug>` from the base branch
     (or the existing branch for fix rounds)
   - repo `setup` script, e.g. OpenAPI client generation
   - one Claude session with the system rules from `worker/prompts.py`
   - the session ends with `{status: done|blocked, summary}`
   - leftovers are committed; then push and open a PR to the base branch. The summary becomes the PR body.
4. **CI**: the delivery loop polls check runs on the PR head.
   - red checks → back to `queued` with `metadata.fix = {kind: "ci"}`. The next round resumes the
     same Claude session.
   - merge conflict → `kind: "conflict"`. The worker merges the base branch first and Claude
     resolves only if conflicts remain.
   - green checks, or no checks after a grace period → squash-merge.
   - `AUTODEV_MAX_FIX_ATTEMPTS` caps the fix rounds.
5. **Deploying**: the change counts as on stage when either
   - the repo's `version_url` reports a commit that contains the merge commit, or
   - (without `version_url`) every push workflow for that commit, or a newer commit containing it,
     succeeded on the base branch.
6. **On stage**: Telegram notification with the stage link and the summary.
7. **Release**: `POST /api/projects/{id}/release`.
   - opens the stage→prod PR
   - the delivery loop merges it with a merge commit once its checks pass. A squash here would
     make the next stage→main PR conflict.
   - then the tasks become `released`.

## Owner actions

- **Cancel**: allowed in queued, in_progress or ci. A running Claude session is stopped within ~5 s.
- **Retry**: allowed in failed or cancelled. The previous error is passed to the agent.
- **Feedback**:
  - before merge — another round on the same PR
  - after merge — a follow-up task that depends on the original
- **Ticks across versions**: a new plan (developer, rebuild) or a follow-up landing on stage starts the
  check over, but a step whose text was ticked before is shown as «Проверено в прошлой версии»
  (`plan_earlier`): visible, but it doesn't count toward «проверено» until ticked again, since the
  new code may have broken it.
- **Rebuild the test plan** («Пересобрать» on the plan, `POST /api/tasks/{id}/plan/refresh`,
  `autodev task refresh-plan <n>…`): main tasks on stage or released. The plan normally grows as
  follow-ups land; a rebuild is for when it didn't (tasks from before one-plan-per-task, bugs or
  changes in that mechanism). The `planner` loop clones the stage branch of every repo the task and
  its landed follow-ups changed, and a read-only Claude session writes the whole plan again. The new
  plan starts the check over; on failure the old plan stays. A follow-up landing meanwhile keeps
  its new steps.
- **Pause everything**: toggle the `developer` agent off in the dashboard (pauses the planner too).

## Chats

A chat is a conversation with an agent about a *subject* (`autodev/chats.py`). Today the subject is a
task: «Спросить» on the task page lists its chats, a chat per question («Новый вопрос»; ❔ next to a
test-plan step starts one quoting the step). A finished chat stays in the list with what it came to
(«доработать → #N»), and a new one starts without its conversation: what earlier chats decided
reaches it through the task's context (its follow-ups, and every approved or rejected proposal).

- The API stores the owner's message and marks the chat `queued`. A chat slot in the worker
  (`AUTODEV_CHAT_SLOTS`, default 2; not paused with the developers) claims it and runs one Claude turn.
- The agent is read-only: a checkout of the project's stage branch at `$AUTODEV_WORKDIR/chats/<chat id>`,
  refreshed before every turn (removed after 3 idle days), no Edit/Write tools. It reads code,
  `gh pr diff`, the stage site.
- One Claude session per chat (`--resume`). The subject's context (task, its plan with ticks,
  follow-ups, QA, project) goes in the first turn, and again whenever it changed. If the session is
  gone, a fresh one gets the context plus the conversation so far.
- Messages written while the agent answers are answered in the next turn. «Стоп» stops the turn.
- The agent never changes anything itself: it returns `{reply, proposals}`. A proposal (a follow-up to
  the task, a new task) waits in its message until the owner taps approve; then the API applies it
  and adds an event message the agent sees next turn.
- To chat about something else (a project's planning chat…), add a `Subject` with its `topic()` and
  actions to `SUBJECTS`; the API, the chat slots and the dashboard's `<ChatSheet>` work as they are.

## Subscription limits

Claude reports a rejected rate limit (`rate_limit_event`), or the result text says the limit was hit.
In that case the task goes back to `queued` and every slot pauses until the reset time.
