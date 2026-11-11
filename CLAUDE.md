# AutoDev

The owner sends a task from a phone; agents (PM → developer → reviewer → PM on stage, plus a scout
that finds work itself) take it to stage. README.md is the owner's manual, docs/ARCHITECTURE.md the
map of the code and of a task's life, docs/DEPLOY.md how it runs. Read the map before changing a flow.

## Commands

```bash
uv sync --extra dev --extra qa
export TEST_DATABASE_URL=postgresql+asyncpg://autodev:autodev@localhost:5432/autodev_test   # tests need Postgres
uv run ruff check . && uv run ruff format --check . && uv run pytest -q
cd dashboard && npm ci && npx tsc --noEmit && npx eslint src
```

CI runs exactly these (`.githooks/pre-push` mirrors it). A schema change is a new file in
`migrations/versions/`; the API and the worker update minutes apart, so keep it backward
compatible (add first, drop in a later change).

## What the owner wants from this code

- **Simple for the owner.** Fewer settings, fewer buttons, sensible defaults; the system decides
  what it can. A new option needs a reason the default can't cover.
- **Readable by a person.** One job per module, stated in its docstring. Comments say why, not what.
  No leftovers: when a feature goes, its code, tests, docs and labels go with it.
- **Prompts are the product.** `autodev/worker/prompts.py` holds every agent's rules. Change them
  as carefully as code, and keep them short: every line is read on every run.
- **Docs move with the code.** A change to a flow updates README.md (what the owner sees, in Russian)
  and docs/ARCHITECTURE.md in the same PR.
- Texts the owner sees are in Russian; code, comments and commits in English.

## Shipping

Branch → PR → green CI → merge to main. The Deploy workflow builds the images and the host's
`autodev-update.timer` rolls out the API, the dashboard and the worker once no agent session is running.
