"""Project configuration models using Pydantic Settings.

All configuration is read from environment variables or a ``.env`` file.
Sensitive values (tokens, passwords) are marked as ``SecretStr`` so they
are never accidentally logged.

TODO: Add per-agent configuration sections.
TODO: Add YAML-based project definition support.
TODO: Add config validation CLI command: ``autodev config validate``.
"""

from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """PostgreSQL connection settings.

    TODO: Add connection pool size configuration.
    """

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
    """Redis connection settings.

    TODO: Add TLS support.
    TODO: Add sentinel / cluster support.
    """

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
    """GitHub integration settings.

    TODO: Add GitHub App (private key) auth support.
    """

    model_config = SettingsConfigDict(env_prefix="GITHUB_")

    token: SecretStr | None = None
    webhook_secret: SecretStr | None = None
    repo: str = ""


class TelegramSettings(BaseSettings):
    """Telegram bot integration settings."""

    model_config = SettingsConfigDict(env_prefix="TELEGRAM_")

    bot_token: SecretStr | None = None
    chat_id: str = ""


class ProjectConfig(BaseSettings):
    """Top-level application configuration.

    Reads from environment variables and an optional ``.env`` file in the
    working directory.

    TODO: Support per-environment config files (dev/staging/prod).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    app_name: str = "AutoDev Framework"
    debug: bool = False
    log_level: str = "INFO"

    # HTTP API
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Sub-settings (nested from prefixed env vars)
    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    github: GitHubSettings = Field(default_factory=GitHubSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
