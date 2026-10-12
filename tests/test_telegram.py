"""Telegram bot: command routing and menu sync."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from autodev.integrations import telegram_pm
from autodev.integrations.telegram_pm import COMMANDS, TelegramPMBot


@pytest.mark.parametrize(
    ("typed", "handler"), [("/status", "_show_tasks"), ("/staging@autodev_agent_bot", "_show_stage")]
)
async def test_v1_command_names_still_work(typed, handler, monkeypatch) -> None:
    bot = TelegramPMBot(token="t", owner_chat_id="1")
    called = AsyncMock()
    monkeypatch.setattr(bot, handler, called)
    monkeypatch.setattr(bot, "send_message", AsyncMock())
    await bot.handle_update({"message": {"chat": {"id": 1}, "text": typed}})
    called.assert_awaited_once_with("1")
    bot.send_message.assert_not_awaited()


async def test_sync_commands_pushes_menu(monkeypatch) -> None:
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append({"path": request.url.path, "body": request.read()})
        return httpx.Response(200, json={"ok": True, "result": True})

    bot = TelegramPMBot(token="t", owner_chat_id="1")
    bot._client = httpx.AsyncClient(base_url="https://api.telegram.org/bott", transport=httpx.MockTransport(handler))
    monkeypatch.setattr(telegram_pm, "get_telegram_bot", AsyncMock(return_value=bot))

    await telegram_pm.sync_commands()

    assert sent[0]["path"].endswith("/setMyCommands")
    for name, _ in COMMANDS:
        assert f'"command":"{name}"'.encode() in sent[0]["body"].replace(b" ", b"")


async def test_sync_commands_without_token_does_nothing(monkeypatch) -> None:
    bot = TelegramPMBot()
    monkeypatch.setattr(telegram_pm, "get_telegram_bot", AsyncMock(return_value=bot))
    await telegram_pm.sync_commands()  # no client created, no exception
    assert bot._client is None


async def test_verify_button_marks_task_checked(session_factory, project, monkeypatch) -> None:
    from autodev.core.models import Task, TaskStatus

    async with session_factory() as s:
        task = Task(
            title="Поиск", project_id=project.id, status=TaskStatus.ON_STAGE, metadata_={"test_plan": ["Открой /"]}
        )
        s.add(task)
        await s.commit()
        await s.refresh(task)

    bot = TelegramPMBot(token="t", owner_chat_id="1")
    monkeypatch.setattr(bot, "answer_callback_query", AsyncMock())
    monkeypatch.setattr(bot, "edit_message_text", AsyncMock())
    callback = {"id": "c", "data": f"ok:{task.id}", "message": {"chat": {"id": 1}, "message_id": 9}}
    await bot.handle_update({"callback_query": callback})

    async with session_factory() as s:
        assert (await s.get(Task, task.id)).metadata_["verified_at"]
    bot.answer_callback_query.assert_awaited_once_with("c", "Отмечено")
    assert "Проверено" in bot.edit_message_text.await_args.args[2]
