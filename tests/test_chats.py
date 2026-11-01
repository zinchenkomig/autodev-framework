"""Chats: the API (messages, stop, approving proposals) and the worker's chat turn."""

from __future__ import annotations

import os
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from autodev.core.claude import ClaudeResult
from autodev.core.config import Settings
from autodev.core.models import Chat, ChatMessage, ChatState, Project, Task, TaskStatus
from autodev.worker import chat as chat_mod
from autodev.worker.context import WorkerContext


async def add_task(session_factory, **kw) -> Task:
    fields = {
        "title": "Фильтр по дате",
        "description": "Добавь фильтр по дате в список заказов",
        "project_id": "shop",
        "repo": "acme/shop",
        "status": TaskStatus.ON_STAGE,
        "pr_number": 7,
        "pr_url": "https://github.com/acme/shop/pull/7",
        "branch": "autodev/1-filter",
        "summary": "Добавил фильтр «Дата» над списком",
        "metadata_": {"test_plan": ["Открой stage", "Нажми «Дата»"], "plan_checked": [0]},
        **kw,
    }
    async with session_factory() as session:
        task = Task(**fields)
        session.add(task)
        await session.commit()
        return task


async def open_chat(client, task: Task) -> dict:
    r = await client.post("/api/chats/", json={"subject": "task", "subject_id": str(task.id)})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


async def test_a_chat_per_question(client, project, session_factory) -> None:
    task = await add_task(session_factory)
    r = await client.post(
        "/api/chats/",
        json={"subject": "task", "subject_id": str(task.id), "text": "Что такое «Дата»?", "quote": "Шаг 2"},
    )
    first = r.json()
    assert first["title"] == f"#{task.ticket_number} Фильтр по дате" and first["project_id"] == "shop"
    assert first["state"] == "queued" and first["question"] == "Что такое «Дата»?"
    assert [(m["role"], m["quote"]) for m in first["messages"]] == [("user", "Шаг 2")]
    assert first["outcome"] == [] and first["pending"] == 0

    second = await open_chat(client, task)  # no question yet: an empty idle chat
    assert second["id"] != first["id"] and second["state"] == "idle" and second["question"] is None
    found = (await client.get("/api/chats/", params={"subject": "task", "subject_id": str(task.id)})).json()
    assert [c["id"] for c in found] == [second["id"], first["id"]]  # newest first

    r = await client.post("/api/chats/", json={"subject": "task", "subject_id": str(uuid.uuid4())})
    assert r.status_code == 404
    assert (await client.post("/api/chats/", json={"subject": "nope"})).status_code == 422


async def test_message_queues_the_chat(client, project, session_factory) -> None:
    task = await add_task(session_factory)
    chat = await open_chat(client, task)
    r = await client.post(
        f"/api/chats/{chat['id']}/messages", json={"text": "Что такое «Дата»?", "quote": "Нажми «Дата»"}
    )
    body = r.json()
    assert body["state"] == "queued"
    assert body["messages"][0] | {"id": None, "created_at": None} == {
        "id": None,
        "role": "user",
        "text": "Что такое «Дата»?",
        "quote": "Нажми «Дата»",
        "proposals": [],
        "created_at": None,
    }

    # Stopping a queued chat just takes it out of the queue.
    assert (await client.post(f"/api/chats/{chat['id']}/stop")).json()["state"] == "idle"


async def test_message_while_answering_waits_for_next_turn(client, project, session_factory) -> None:
    task = await add_task(session_factory)
    chat = await open_chat(client, task)
    async with session_factory() as session:
        row = await session.get(Chat, uuid.UUID(chat["id"]))
        row.state = ChatState.ANSWERING
        await session.commit()
    body = (await client.post(f"/api/chats/{chat['id']}/messages", json={"text": "И ещё"})).json()
    assert body["state"] == "answering"
    body = (await client.post(f"/api/chats/{chat['id']}/stop")).json()
    assert body["state"] == "answering" and body["stopping"] is True
    assert (await client.delete(f"/api/chats/{chat['id']}")).status_code == 409


async def add_proposal(session_factory, chat_id: str, *proposals: dict) -> str:
    async with session_factory() as session:
        message = ChatMessage(
            chat_id=uuid.UUID(chat_id),
            role="assistant",
            text="Похоже на баг",
            proposals=[{"state": "pending", **p} for p in proposals],
        )
        session.add(message)
        await session.commit()
        return str(message.id)


async def test_approve_follow_up_creates_it_under_the_main_task(client, project, session_factory) -> None:
    task = await add_task(session_factory, metadata_={"test_plan": ["a"], "verified_at": "2026-10-30T00:00:00"})
    chat = await open_chat(client, task)
    mid = await add_proposal(
        session_factory,
        chat["id"],
        {"action": "follow_up", "title": "Фильтр сбрасывается", "description": "После обновления страницы…"},
        {"action": "new_task", "title": "Экспорт в CSV", "description": "Кнопка экспорта"},
    )
    url = f"/api/chats/{chat['id']}/messages/{mid}/proposals"

    assert (await client.get(f"/api/chats/{chat['id']}")).json()["pending"] == 2
    body = (await client.post(f"{url}/0", json={"approve": True})).json()
    proposal = body["messages"][0]["proposals"][0]
    assert proposal["state"] == "applied" and proposal["label"] == "Доработать"
    assert body["messages"][-1]["role"] == "event"
    assert body["messages"][-1]["text"] == f"Создана доработка #{proposal['result']['ticket_number']}"
    assert (await client.post(f"{url}/0", json={"approve": True})).status_code == 409

    body = (await client.post(f"{url}/1", json={"approve": False})).json()
    assert body["messages"][0]["proposals"][1]["state"] == "rejected"
    assert body["pending"] == 0
    assert [(o["label"], o["state"], o["ticket_number"]) for o in body["outcome"]] == [
        ("Доработать", "applied", proposal["result"]["ticket_number"]),
        ("Создать задачу", "rejected", None),
    ]
    assert body["messages"][-1]["text"] == "Отклонено: Экспорт в CSV"
    assert (await client.post(f"{url}/2", json={"approve": True})).status_code == 404

    async with session_factory() as session:
        follow_up = await session.get(Task, uuid.UUID(proposal["result"]["task_id"]))
        main = await session.get(Task, task.id)
        tasks = (await session.execute(select(Task))).scalars().all()
    assert follow_up.parent_id == task.id and follow_up.created_by == "chat"
    assert follow_up.description.startswith("Фильтр сбрасывается\n\nПосле обновления страницы…")
    assert "verified_at" not in main.metadata_  # the main task is checked again
    assert len(tasks) == 2  # the rejected one wasn't created


async def test_approve_new_task(client, project, session_factory) -> None:
    task = await add_task(session_factory)
    chat = await open_chat(client, task)
    mid = await add_proposal(
        session_factory, chat["id"], {"action": "new_task", "title": "Экспорт в CSV", "description": "Кнопка"}
    )
    body = (await client.post(f"/api/chats/{chat['id']}/messages/{mid}/proposals/0", json={"approve": True})).json()
    ref = body["messages"][0]["proposals"][0]["result"]
    async with session_factory() as session:
        new = await session.get(Task, uuid.UUID(ref["task_id"]))
    assert new.title == "Экспорт в CSV" and new.parent_id is None and new.project_id == "shop"
    assert new.status == TaskStatus.QUEUED and new.created_by == "chat"


async def test_approve_principle_appends_it_to_the_project(client, project, session_factory) -> None:
    task = await add_task(session_factory)
    chat = await open_chat(client, task)
    for text in ("Подпись совпадает\nс поведением", "Меньше тапов"):
        mid = await add_proposal(
            session_factory, chat["id"], {"action": "principle", "title": "Принцип", "description": text}
        )
        r = await client.post(f"/api/chats/{chat['id']}/messages/{mid}/proposals/0", json={"approve": True})
        assert r.status_code == 200, r.text
    async with session_factory() as session:
        assert (await session.get(Project, "shop")).principles == "- Подпись совпадает с поведением\n- Меньше тапов"


async def test_follow_up_that_cant_be_taken_stays_pending(client, project, session_factory) -> None:
    task = await add_task(session_factory, status=TaskStatus.IN_PROGRESS)
    chat = await open_chat(client, task)
    mid = await add_proposal(session_factory, chat["id"], {"action": "follow_up", "title": "x", "description": "y"})
    r = await client.post(f"/api/chats/{chat['id']}/messages/{mid}/proposals/0", json={"approve": True})
    assert r.status_code == 409
    body = (await client.get(f"/api/chats/{chat['id']}")).json()
    assert body["messages"][0]["proposals"][0]["state"] == "pending"


async def test_deleting_the_task_deletes_its_chat(client, project, session_factory) -> None:
    task = await add_task(session_factory)
    chat = await open_chat(client, task)
    assert (await client.delete(f"/api/tasks/{task.id}")).status_code == 204
    assert (await client.get(f"/api/chats/{chat['id']}")).status_code == 404


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


class FakeRunner:
    calls: list[dict] = []
    results: list[ClaudeResult] = []
    options: dict = {}
    during = None  # async callable run while the agent "works"

    def __init__(self, cwd, **kw) -> None:
        FakeRunner.options = {"cwd": cwd, **kw}

    async def run(self, prompt, *, resume=None, on_log=None, should_cancel=None):
        FakeRunner.calls.append({"prompt": prompt, "resume": resume})
        if on_log:
            await on_log("info", "🔧 Grep: Дата", None)
        if FakeRunner.during:
            await FakeRunner.during()
            FakeRunner.during = None
        return FakeRunner.results.pop(0)


def reply(text: str = "Это фильтр по дате создания", proposals=(), session: str = "s1") -> ClaudeResult:
    return ClaudeResult(
        ok=True, summary="", session_id=session, data={"reply": text, "proposals": list(proposals)}, num_turns=1
    )


@pytest.fixture
def ctx(monkeypatch, tmp_path, session_factory):
    FakeRunner.calls, FakeRunner.results, FakeRunner.during = [], [], None
    monkeypatch.setattr(chat_mod, "ClaudeRunner", FakeRunner)

    async def checkout(ctx, chat_id, project):
        return str(tmp_path)

    monkeypatch.setattr(chat_mod, "checkout", checkout)
    return WorkerContext(settings=Settings(AUTODEV_WORKDIR=str(tmp_path)), session_factory=session_factory)


async def ask(client, chat: dict, text: str, quote: str | None = None) -> None:
    await client.post(f"/api/chats/{chat['id']}/messages", json={"text": text, "quote": quote})


async def turn(ctx) -> uuid.UUID | None:
    chat_id = await chat_mod.claim(ctx)
    if chat_id is not None:
        await chat_mod.answer(ctx, chat_id)
    return chat_id


async def test_turns_resume_one_session(client, project, session_factory, ctx) -> None:
    task = await add_task(session_factory)
    chat = await open_chat(client, task)
    await ask(client, chat, "Что такое «Дата»?", quote="Нажми «Дата»")
    FakeRunner.results = [
        reply(proposals=[{"action": "follow_up", "title": "t", "description": "d"}, {"action": "deploy"}]),
        reply("Да", session="s1"),
    ]

    assert await turn(ctx) is not None
    first = FakeRunner.calls[0]
    assert first["resume"] is None
    assert "# Context" in first["prompt"] and "Нажми «Дата»" in first["prompt"]
    assert "1. [x] Открой stage" in first["prompt"] and "2. [ ] Нажми «Дата»" in first["prompt"]
    assert "Owner: [about: «Нажми «Дата»»]\nЧто такое «Дата»?" in first["prompt"]
    assert FakeRunner.options["disallowed_tools"] == chat_mod.READ_ONLY
    assert "follow_up:" in FakeRunner.options["system_prompt_append"]
    assert FakeRunner.options["schema"]["properties"]["proposals"]["items"]["properties"]["action"]["enum"] == [
        "follow_up",
        "new_task",
        "principle",
    ]

    body = (await client.get(f"/api/chats/{chat['id']}")).json()
    assert body["state"] == "idle" and body["activity"] is None
    answer = body["messages"][-1]
    assert answer["role"] == "assistant" and answer["text"] == "Это фильтр по дате создания"
    assert [p["action"] for p in answer["proposals"]] == ["follow_up"]  # unknown actions dropped

    assert await turn(ctx) is None  # nothing new

    await ask(client, chat, "А где он?")
    await turn(ctx)
    second = FakeRunner.calls[1]
    assert second["resume"] == "s1"
    assert "Context" not in second["prompt"]  # unchanged since the last turn
    assert second["prompt"].endswith("Owner: А где он?")


async def test_changed_context_is_sent_again(client, project, session_factory, ctx) -> None:
    task = await add_task(session_factory)
    chat = await open_chat(client, task)
    await ask(client, chat, "?")
    FakeRunner.results = [reply(), reply()]
    await turn(ctx)

    async with session_factory() as session:
        row = await session.get(Task, task.id)
        row.metadata_ = {**row.metadata_, "plan_checked": [0, 1]}
        await session.commit()
    await ask(client, chat, "Всё проверил")
    await turn(ctx)
    assert "# Updated context" in FakeRunner.calls[1]["prompt"]
    assert "2. [x] Нажми «Дата»" in FakeRunner.calls[1]["prompt"]


async def test_lost_session_starts_fresh_with_history(client, project, session_factory, ctx) -> None:
    task = await add_task(session_factory)
    chat = await open_chat(client, task)
    await ask(client, chat, "Первый вопрос")
    FakeRunner.results = [
        reply("Первый ответ"),
        ClaudeResult(ok=False, summary="No conversation found", session_missing=True),
        reply("Второй ответ", session="s2"),
    ]
    await turn(ctx)
    await ask(client, chat, "Второй вопрос")
    await turn(ctx)

    fresh = FakeRunner.calls[2]
    assert fresh["resume"] is None
    assert "# Context" in fresh["prompt"]
    assert "Owner: Первый вопрос\nYou: Первый ответ" in fresh["prompt"]
    assert fresh["prompt"].endswith("# New in the chat\n\nOwner: Второй вопрос")
    async with session_factory() as session:
        assert (await session.get(Chat, uuid.UUID(chat["id"]))).session_id == "s2"


async def test_message_during_answer_queues_another_turn(client, project, session_factory, ctx) -> None:
    task = await add_task(session_factory)
    chat = await open_chat(client, task)
    await ask(client, chat, "Первый")
    FakeRunner.during = lambda: ask(client, chat, "Второй")  # arrives while the agent is answering
    FakeRunner.results = [reply(), reply()]
    await turn(ctx)
    assert FakeRunner.calls[0]["prompt"].endswith("Owner: Первый")
    assert (await client.get(f"/api/chats/{chat['id']}")).json()["state"] == "queued"

    await turn(ctx)
    assert FakeRunner.calls[1]["prompt"].endswith("Owner: Второй")
    assert (await client.get(f"/api/chats/{chat['id']}")).json()["state"] == "idle"


async def test_rate_limit_requeues_and_pauses(client, project, session_factory, ctx) -> None:
    task = await add_task(session_factory)
    chat = await open_chat(client, task)
    await ask(client, chat, "?")
    until = datetime.now(UTC) + timedelta(hours=1)
    FakeRunner.results = [ClaudeResult(ok=False, summary="limit", rate_limited_until=until)]
    await turn(ctx)
    body = (await client.get(f"/api/chats/{chat['id']}")).json()
    assert body["state"] == "queued" and "Лимит Claude" in body["activity"]
    assert ctx.paused_until == until and body["messages"][-1]["role"] == "user"


async def test_failure_and_stop_are_recorded(client, project, session_factory, ctx) -> None:
    task = await add_task(session_factory)
    chat = await open_chat(client, task)
    await ask(client, chat, "?")
    FakeRunner.results = [ClaudeResult(ok=False, summary="boom"), ClaudeResult(ok=False, summary="", cancelled=True)]
    await turn(ctx)
    body = (await client.get(f"/api/chats/{chat['id']}")).json()
    assert body["state"] == "idle" and body["messages"][-1] | {"id": 0, "created_at": 0} == {
        "id": 0,
        "role": "error",
        "text": "boom",
        "quote": None,
        "proposals": [],
        "created_at": 0,
    }

    await ask(client, chat, "Ещё раз")
    await turn(ctx)
    body = (await client.get(f"/api/chats/{chat['id']}")).json()
    assert [m["role"] for m in body["messages"]] == ["user", "error", "user", "event"]
    assert body["messages"][-1]["text"] == "Остановлено" and body["stopping"] is False


async def test_chat_about_a_deleted_task(client, project, session_factory, ctx) -> None:
    task = await add_task(session_factory)
    chat = await open_chat(client, task)
    await ask(client, chat, "?")
    async with session_factory() as session:
        await session.delete(await session.get(Task, task.id))
        await session.commit()
    await turn(ctx)
    body = (await client.get(f"/api/chats/{chat['id']}")).json()
    assert body["state"] == "idle" and body["messages"][-1]["role"] == "error"
    assert FakeRunner.calls == []


async def test_recover_after_restart(session_factory, project, ctx) -> None:
    async with session_factory() as session:
        session.add_all(
            [
                Chat(subject="task", title="a", state=ChatState.ANSWERING, metadata_={}),
                Chat(subject="task", title="b", state=ChatState.ANSWERING, metadata_={"stop": True}),
            ]
        )
        await session.commit()
    await chat_mod.recover(ctx)
    async with session_factory() as session:
        states = {c.title: (c.state, c.metadata_) for c in (await session.execute(select(Chat))).scalars()}
    assert states == {"a": ("queued", {}), "b": ("idle", {})}


def test_sweep_removes_idle_checkouts(tmp_path) -> None:
    old, fresh = tmp_path / "chats" / "old", tmp_path / "chats" / "fresh"
    old.mkdir(parents=True)
    fresh.mkdir()
    (old / "file").write_text("x")
    week_ago = time.time() - 7 * 24 * 3600
    os.utime(old, (week_ago, week_ago))
    chat_mod.sweep(str(tmp_path))
    assert not old.exists() and fresh.exists()


async def test_next_chat_knows_what_earlier_chats_decided(client, project, session_factory, ctx) -> None:
    task = await add_task(session_factory)
    earlier = await open_chat(client, task)
    mid = await add_proposal(
        session_factory,
        earlier["id"],
        {"action": "new_task", "title": "Экспорт в CSV", "description": "Кнопка"},
        {"action": "follow_up", "title": "Сброс фильтра", "description": "…"},
    )
    url = f"/api/chats/{earlier['id']}/messages/{mid}/proposals"
    ticket = (await client.post(f"{url}/0", json={"approve": True})).json()["outcome"][0]["ticket_number"]
    await client.post(f"{url}/1", json={"approve": False})

    r = await client.post("/api/chats/", json={"subject": "task", "subject_id": str(task.id), "text": "Новый вопрос"})
    assert r.json()["id"] != earlier["id"]
    FakeRunner.results = [reply()]
    await turn(ctx)
    prompt = FakeRunner.calls[0]["prompt"]
    assert f"- approved new_task «Экспорт в CSV» → task #{ticket}" in prompt
    assert "- rejected follow_up «Сброс фильтра»" in prompt
    assert "Owner: Новый вопрос" in prompt and "Похоже на баг" not in prompt  # not the other chat's talk
