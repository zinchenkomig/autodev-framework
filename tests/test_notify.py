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


async def test_follow_up_on_stage_sends_the_main_task_plan(sent) -> None:
    main = Task(id=uuid.uuid4(), ticket_number=3, title="Экран", metadata_={"test_plan": ["Открой stage", "Фильтр"]})
    child = task(root_plan={"base": [], "plan": ["свой"]})
    await notify.on_stage(child, None, main=main)

    assert "доработка к" in sent.await_args_list[0].args[0] and "#3 Экран" in sent.await_args_list[0].args[0]
    plan = sent.await_args_list[1].args[0]
    assert "Как проверить #3" in plan and "2. Фильтр" in plan
    button = sent.await_args_list[1].kwargs["reply_markup"]["inline_keyboard"][0][0]
    assert button["callback_data"] == f"ok:{main.id}"


def test_summary_markdown_becomes_telegram_html():
    assert notify._markdown("**Ключевые решения** <x> `a<b`") == "<b>Ключевые решения</b> &lt;x&gt; <code>a&lt;b</code>"


async def test_accepted_says_what_the_pm_found(sent) -> None:
    ok = task(test_plan=["Открой stage"], acceptance={"state": "accepted", "summary": "Прошёл план <без> ошибок"})
    await notify.accepted(ok, None, screenshot=b"png")
    text = sent.await_args_list[0].args[0]
    assert text.startswith("✅") and "PM проверил и принял" in text and "&lt;без&gt;" in text
    assert sent.await_args_list[0].kwargs["photo"] == b"png" and sent.await_count == 2  # and the plan

    sent.reset_mock()
    left = {"state": "concerns", "fixes": 2, "summary": "Почти", "issues": ["Иконка ±"]}
    await notify.accepted(task(acceptance=left), None)
    text = sent.await_args.args[0]
    assert text.startswith("⚠️") and "после 2 доработок" in text and "• Иконка ±" in text
