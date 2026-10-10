# API image (dashboard backend + Telegram webhook). The worker runs on the
# host instead — see README.md — because it needs Claude Code, git and
# full access to build and test target projects.
FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --no-dev --frozen --no-install-project

COPY autodev/ autodev/
COPY migrations/ migrations/
COPY alembic.ini autodev.yaml ./
RUN uv sync --no-dev --frozen

ENV AUTODEV_ROLE=api \
    AUTODEV_PORT=8000

EXPOSE 8000

CMD ["uv", "run", "--no-sync", "python", "-m", "autodev"]
