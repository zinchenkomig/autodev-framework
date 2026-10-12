"""Owner notifications: what goes into the Telegram messages."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from autodev import notify
from autodev.core.models import Task
from autodev.worker import qa


@pytest.fixture
def sent(monkeypatch) -> AsyncMock:
    send = AsyncMock()
    monkeypatch.setattr(notify, "_send", send)
    return send


def task(**metadata) -> Task:
    return Task(id=uuid.uuid4(), ticket_number=7, title="Поиск", summary="Добавил поиск", metadata_=metadata)


async def test_on_stage_sends_test_plan_as_separate_message(sent) -> None:
    await notify.on_stage(task(test_plan=["Открой /users", "Введи <ann>"]), None, screenshot=b"png")

    assert sent.await_count == 2
    assert sent.await_args_list[0].kwargs["photo"] == b"png"
    plan = sent.await_args_list[1].args[0]
    assert "Как проверить #7" in plan and "1. Открой /users\n2. Введи &lt;ann&gt;" in plan
    button = sent.await_args_list[1].kwargs["reply_markup"]["inline_keyboard"][0][0]
    assert button["callback_data"].startswith("ok:")


async def test_on_stage_without_plan_or_with_broken_qa_sends_one_message(sent) -> None:
    await notify.on_stage(task(), None)
    broken = qa.QAResult(pages=[qa.PageResult(url="https://x/", status=500, problems=["HTTP 500"])])
    await notify.on_stage(task(test_plan=["Открой /users"]), None, qa=broken)

    assert sent.await_count == 2  # one per call
