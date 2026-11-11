"""Things every worker loop needs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from autodev.core.config import Settings
from autodev.core.models import PAUSED_UNTIL_SETTING, Setting
from autodev.core.shell import git_env
from autodev.integrations.github import GitHubClient
from autodev.worker.store import Store


@dataclass
class WorkerContext:
    settings: Settings
    session_factory: async_sessionmaker[AsyncSession]
    store: Store = field(init=False)
    # Set when Claude reports the subscription limit; slots wait until then.
    paused_until: datetime | None = None

    def __post_init__(self) -> None:
        self.store = Store(self.session_factory)

    def github(self) -> GitHubClient:
        return GitHubClient(token=self.settings.github_token)

    def env(self) -> dict[str, str]:
        return git_env(self.settings.github_token)

    async def pause(self, until: datetime) -> None:
        """Claude's limit is hit: every loop waits until *until*, and the dashboard's header says so."""
        self.paused_until = until
        async with self.session_factory() as session:
            await session.merge(Setting(key=PAUSED_UNTIL_SETTING, value=until.isoformat()))
            await session.commit()

    def paused(self) -> bool:
        return self.paused_until is not None and datetime.now(UTC) < self.paused_until
