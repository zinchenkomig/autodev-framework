"""Project configuration models using Pydantic.

Two layers of configuration:
1. **AppSettings** — runtime settings read from environment variables / ``.env``
   (tokens, DB connection, ports, etc.).
2. **ProjectConfig** — project-level declarative config loaded from a YAML file
   (repos, agents, environments, release strategy, notifications).

Usage::

    from autodev.core.config import load_config, save_config

    cfg = load_config("autodev.yaml")
    print(cfg.name)

    save_config(cfg, "autodev.yaml")
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# Runtime / environment settings (unchanged)
# ---------------------------------------------------------------------------


class DatabaseSettings(BaseSettings):
    """PostgreSQL connection settings."""

    model_config = SettingsConfigDict(env_prefix="DB_")

    host: str = "localhost"
    port: int = 5432
    name: str = "autodev"
    user: str = "autodev"
    password: SecretStr = Field(default=SecretStr("autodev"))

    @property
    def url(self) -> str:
        """Async SQLAlchemy connection URL."""
        pwd = self.password.get_secret_value()
        return f"postgresql+asyncpg://{self.user}:{pwd}@{self.host}:{self.port}/{self.name}"


class RedisSettings(BaseSettings):
    """Redis connection settings."""

    model_config = SettingsConfigDict(env_prefix="REDIS_")

    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: SecretStr | None = None

    @property
    def url(self) -> str:
        """Redis connection URL."""
        pwd = self.password.get_secret_value() if self.password else None
        auth = f":{pwd}@" if pwd else ""
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"


class GitHubSettings(BaseSettings):
    """GitHub integration settings."""

    model_config = SettingsConfigDict(env_prefix="GITHUB_")

    token: SecretStr | None = None
    webhook_secret: SecretStr | None = None
    repo: str = ""


class TelegramSettings(BaseSettings):
    """Telegram bot integration settings."""

    model_config = SettingsConfigDict(env_prefix="TELEGRAM_")

    bot_token: SecretStr | None = None
    chat_id: str = ""


class AppSettings(BaseSettings):
    """Top-level application runtime configuration.

    Reads from environment variables and an optional ``.env`` file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    app_name: str = "AutoDev Framework"
    debug: bool = False
    log_level: str = "INFO"

    api_host: str = "0.0.0.0"
    api_port: int = 8000

    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    github: GitHubSettings = Field(default_factory=GitHubSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)


# ---------------------------------------------------------------------------
# YAML-based project configuration (Pydantic models)
# ---------------------------------------------------------------------------


class RepoConfig(BaseModel):
    """Configuration for a single source repository."""

    name: str
    url: str
    language: str = "python"
    context_file: str = "CLAUDE.md"
    tests_command: str = "pytest tests/"
    lint_command: str = "ruff check ."


class EnvironmentConfig(BaseModel):
    """Deployment environment (staging, production, etc.)."""

    name: str
    url: str
    deploy_command: str
    requires_approval: bool = False


class TriggerType(StrEnum):
    schedule = "schedule"
    event = "event"


class AgentTrigger(BaseModel):
    """A trigger that causes an agent to run."""

    type: TriggerType
    value: str


class AgentConfig(BaseModel):
    """Configuration for an autonomous agent."""

    role: str
    runner: str = "claude-code"
    model: str = "claude-sonnet-4"
    max_iterations: int = 20
    triggers: list[AgentTrigger] = Field(default_factory=list)
    instructions: str = ""
    tools: list[str] = Field(default_factory=list)


class BranchStrategy(StrEnum):
    gitflow = "gitflow"
    trunk = "trunk"


class ReleaseConfig(BaseModel):
    """Release and branching strategy configuration."""

    branch_strategy: BranchStrategy = BranchStrategy.gitflow
    min_prs: int = 1
    auto_deploy_staging: bool = True
    require_human_approval: bool = True


class NotificationType(StrEnum):
    telegram = "telegram"
    slack = "slack"
    webhook = "webhook"


class NotificationTarget(BaseModel):
    """A single notification destination."""

    type: NotificationType
    config: dict[str, Any] = Field(default_factory=dict)


class NotificationConfig(BaseModel):
    """Aggregated notification settings."""

    targets: list[NotificationTarget] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)


class ProjectConfig(BaseModel):
    """Top-level YAML project configuration."""

    name: str
    repos: list[RepoConfig] = Field(default_factory=list)
    environments: list[EnvironmentConfig] = Field(default_factory=list)
    agents: list[AgentConfig] = Field(default_factory=list)
    release: ReleaseConfig = Field(default_factory=ReleaseConfig)
    notifications: NotificationConfig = Field(default_factory=NotificationConfig)


# ---------------------------------------------------------------------------
# Load / save helpers
# ---------------------------------------------------------------------------


def load_config(path: str) -> ProjectConfig:
    """Load a :class:`ProjectConfig` from a YAML file.

    Args:
        path: Path to the YAML configuration file.

    Returns:
        Validated :class:`ProjectConfig` instance.

    Raises:
        FileNotFoundError: If *path* does not exist.
        yaml.YAMLError: If the file is not valid YAML.
        pydantic.ValidationError: If the data does not match the schema.
    """
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if data is None:
        data = {}
    return ProjectConfig.model_validate(data)


def save_config(config: ProjectConfig, path: str) -> None:
    """Serialize a :class:`ProjectConfig` to a YAML file.

    Args:
        config: The configuration object to save.
        path: Destination file path.  Parent directories are created if needed.
    """
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        yaml.dump(
            config.model_dump(mode="json"),
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
