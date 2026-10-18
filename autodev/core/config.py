"""Configuration.

Two layers:

1. :class:`Settings` — runtime settings from environment variables
   (DB, tokens, worker sizing, timeouts).
2. :class:`AutodevConfig` — ``autodev.yaml``. It seeds the ``projects``
   table on startup; projects that already exist in the DB are left alone, so
   the dashboard stays the place to edit them. ``${VAR}`` references are
   expanded from the environment.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import AliasChoices, BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# Runtime settings
# ---------------------------------------------------------------------------


class Settings(BaseSettings):
    """Runtime settings read from the environment (and ``.env``)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = Field(
        default="postgresql+asyncpg://autodev:autodev@localhost:5432/autodev",
        validation_alias="DATABASE_URL",
    )
    github_token: str = Field(default="", validation_alias=AliasChoices("GITHUB_TOKEN", "GH_TOKEN"))
    config_path: str = Field(default="autodev.yaml", validation_alias="AUTODEV_CONFIG")

    # Which loops this process runs: "api", "worker" or "all".
    role: str = Field(default="all", validation_alias="AUTODEV_ROLE")
    host: str = Field(default="0.0.0.0", validation_alias="AUTODEV_HOST")
    port: int = Field(default=8000, validation_alias="AUTODEV_PORT")

    # Claude Code. Empty model = the CLI's default for the account.
    model: str = Field(default="", validation_alias="AUTODEV_MODEL")
    claude_bin: str = Field(default="claude", validation_alias="AUTODEV_CLAUDE_BIN")
    claude_timeout: int = Field(default=45 * 60, validation_alias="AUTODEV_CLAUDE_TIMEOUT")

    # Worker
    workdir: str = Field(default="/work", validation_alias="AUTODEV_WORKDIR")
    worker_slots: int = Field(default=2, validation_alias="AUTODEV_WORKER_SLOTS")
    poll_interval: float = Field(default=10.0, validation_alias="AUTODEV_POLL_INTERVAL")
    # While this file exists no new tasks are started (autodev-update.sh drains before restarting).
    drain_file: str = Field(default="/run/autodev/drain", validation_alias="AUTODEV_DRAIN_FILE")
    max_fix_attempts: int = Field(default=3, validation_alias="AUTODEV_MAX_FIX_ATTEMPTS")
    # How long a PR may sit without any check run before it is merged anyway.
    checks_grace_seconds: int = Field(default=120, validation_alias="AUTODEV_CHECKS_GRACE")
    ci_timeout: int = Field(default=60 * 60, validation_alias="AUTODEV_CI_TIMEOUT")
    deploy_timeout: int = Field(default=20 * 60, validation_alias="AUTODEV_DEPLOY_TIMEOUT")

    # Public URL of the dashboard, used for links in notifications.
    public_url: str = Field(default="", validation_alias="AUTODEV_PUBLIC_URL")
    # htpasswd file with the dashboard's users (see autodev/api/routes/auth.py).
    htpasswd: str = Field(default="", validation_alias="AUTODEV_HTPASSWD")


@lru_cache
def get_settings() -> Settings:
    return Settings()


# ---------------------------------------------------------------------------
# autodev.yaml
# ---------------------------------------------------------------------------


class RepoSpec(BaseModel):
    """The repository of a project (a monorepo when the project has several apps)."""

    name: str  # owner/repo
    # URL on stage that returns the deployed commit SHA (JSON or plain text).
    version_url: str | None = None
    # Shell run in the fresh checkout before Claude starts (codegen etc.).
    setup: str | None = None


class ProjectSpec(BaseModel):
    """A project: one repo and its stage environment."""

    slug: str
    name: str
    repos: list[RepoSpec] = Field(min_length=1, max_length=1)
    base_branch: str = "stage"
    prod_branch: str = "main"
    stage_url: str | None = None
    smoke_paths: list[str] = Field(default_factory=list)
    instructions: str | None = None
    model: str | None = None
    max_parallel: int = 1
    enabled: bool = True


class AutodevConfig(BaseModel):
    projects: list[ProjectSpec] = Field(default_factory=list)


_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_env(text: str) -> str:
    return _ENV_REF.sub(lambda m: os.environ.get(m.group(1), ""), text)


def load_config(path: str | Path) -> AutodevConfig:
    """Load ``autodev.yaml``. A missing file yields an empty config."""
    path = Path(path)
    if not path.exists():
        return AutodevConfig()
    data = yaml.safe_load(_expand_env(path.read_text(encoding="utf-8"))) or {}
    return AutodevConfig.model_validate(data)
