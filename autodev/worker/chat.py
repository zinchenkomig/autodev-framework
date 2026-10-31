"""Chat slots: answer the owner's messages in chats (see :mod:`autodev.chats`).

The API stores the owner's message and marks the chat ``queued``; a chat slot
claims it, runs one read-only Claude turn in a checkout of the project's stage
branch and stores the reply with any proposed actions.

A chat keeps one Claude session for the whole conversation (``--resume``), in a
checkout at ``$AUTODEV_WORKDIR/chats/<chat id>`` that stays between turns (a
session is keyed by its directory) and is refreshed before each turn. Checkouts
of chats idle for a few days are removed.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, true

from autodev import chats
from autodev.core import shell
from autodev.core.claude import ClaudeResult, ClaudeRunner
from autodev.core.models import Chat, ChatMessage, ChatState, Project
from autodev.worker import prompts
from autodev.worker.context import WorkerContext

logger = logging.getLogger(__name__)

#: The agent only reads; the checkout is reset before every turn anyway.
READ_ONLY = ["Edit", "MultiEdit", "Write", "NotebookEdit"]
#: Messages a fresh session gets when the old one can't be resumed.
HISTORY = 30
#: Checkouts of chats idle this long are removed (the next turn clones again).
KEEP_CHECKOUT_SECONDS = 3 * 24 * 3600
STOP = "stop"  # metadata flag: the owner pressed stop


async def claim(ctx: WorkerContext) -> uuid.UUID | None:
    """The oldest chat waiting for an answer, now marked answering."""
    async with ctx.session_factory() as session:
        chat = (
            await session.execute(
                select(Chat)
                .where(Chat.state == ChatState.QUEUED)
                .order_by(Chat.updated_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if chat is None:
            return None
        chat.state = ChatState.ANSWERING
        chat.activity = "Читаю…"
        await session.commit()
        return chat.id


async def recover(ctx: WorkerContext) -> None:
    """Chats a previous process was answering go back to the queue (or stop, if the owner asked)."""
    async with ctx.session_factory() as session:
        for chat in (await session.execute(select(Chat).where(Chat.state == ChatState.ANSWERING))).scalars():
            stopped = STOP in (chat.metadata_ or {})
            chat.state = ChatState.IDLE if stopped else ChatState.QUEUED
            chat.activity = None
            chat.metadata_ = {k: v for k, v in (chat.metadata_ or {}).items() if k != STOP}
        await session.commit()


async def answer(ctx: WorkerContext, chat_id: uuid.UUID) -> None:
    """One agent turn for a chat that is already ``answering``."""
    async with ctx.session_factory() as session:
        chat = await session.get(Chat, chat_id)
        if chat is None:
            return
        messages = list(
            (
                await session.execute(
                    select(ChatMessage).where(ChatMessage.chat_id == chat_id).order_by(ChatMessage.created_at)
                )
            ).scalars()
        )
        subject = chats.SUBJECTS.get(chat.subject)
        topic = await subject.topic(session, chat.subject_id) if subject else None
    seen = messages[-1].created_at if messages else None

    if subject is None or topic is None:
        await _finish(ctx, chat_id, seen, error="Не нашёл, о чём этот чат: задачу удалили?")
        return
    new, history = _split(messages, (chat.metadata_ or {}).get("seen"))
    if not any(m.role == "user" for m in new):
        await _finish(ctx, chat_id, seen)
        return

    async def activity(level: str, message: str, details: str | None = None) -> None:
        if message.startswith("🔧"):
            await _set_activity(ctx, chat_id, message.removeprefix("🔧").strip())

    async def stopped() -> bool:
        async with ctx.session_factory() as session:
            current = await session.get(Chat, chat_id)
            return current is None or STOP in (current.metadata_ or {})

    try:
        cwd = await checkout(ctx, chat_id, topic.project)
        runner = ClaudeRunner(
            cwd,
            model=(topic.project.model if topic.project else None) or ctx.settings.model,
            timeout=ctx.settings.chat_timeout,
            env=ctx.env(),
            system_prompt_append=prompts.CHAT_SYSTEM + "\n" + subject.instructions(),
            schema=subject.schema(),
            disallowed_tools=READ_ONLY,
        )
        known = (chat.metadata_ or {}).get("context_digest")
        result: ClaudeResult | None = None
        if chat.session_id:
            context = topic.context if known != topic.digest else None
            result = await runner.run(
                prompts.chat_turn(new, context), resume=chat.session_id, on_log=activity, should_cancel=stopped
            )
            if result.session_missing:
                logger.info("chat %s: session %s is gone, starting a fresh one", chat_id, chat.session_id)
                result = None
        if result is None:
            prompt = prompts.chat_turn(new, topic.context, fresh=True, history=history[-HISTORY:])
            result = await runner.run(prompt, on_log=activity, should_cancel=stopped)
    except Exception as exc:
        logger.exception("chat %s crashed", chat_id)
        await _finish(ctx, chat_id, seen, error=f"{type(exc).__name__}: {exc}")
        return

    if result.rate_limited:
        ctx.paused_until = result.rate_limited_until
        await _requeue(ctx, chat_id, f"Лимит Claude — отвечу после {result.rate_limited_until:%H:%M} UTC")
        return
    reply = str(result.data.get("reply") or "").strip()
    if result.cancelled:
        await _finish(ctx, chat_id, seen, session_id=result.session_id, event="Остановлено")
    elif not result.ok or not reply:
        await _finish(ctx, chat_id, seen, session_id=result.session_id, error=result.summary or "Агент не ответил")
    else:
        logger.info("chat %s answered: %d turns, $%.2f", chat_id, result.num_turns, result.cost_usd)
        await _finish(
            ctx,
            chat_id,
            seen,
            session_id=result.session_id,
            digest=topic.digest,
            reply=ChatMessage(chat_id=chat_id, role="assistant", text=reply, proposals=subject.proposals(
                result.data.get("proposals")
            )),
        )  # fmt: skip


def _split(messages: list[ChatMessage], seen: str | None) -> tuple[list[ChatMessage], list[ChatMessage]]:
    """(the owner's messages and events the agent hasn't seen, the conversation before them).

    *seen* is the time of the last message an earlier turn took in. The time and not the agent's
    last answer: a message that came in while the agent was answering is older than that answer.
    """
    after = datetime.fromisoformat(seen) if seen else None
    new = [m for m in messages if m.role in ("user", "event") and (after is None or m.created_at > after)]
    return new, [m for m in messages if m not in new]


async def checkout(ctx: WorkerContext, chat_id: uuid.UUID, project: Project | None) -> str:
    """The chat's directory with the project's stage branch, fresh. Without a repo: an empty directory."""
    path = Path(ctx.settings.workdir) / "chats" / str(chat_id)
    repo = project.repo() if project else None
    if repo is None:
        path.mkdir(parents=True, exist_ok=True)
    elif not await _refresh(path, project.base_branch, ctx.env()):
        shutil.rmtree(path, ignore_errors=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        await shell.run(
            "git", "clone", "-q", "--filter=blob:none", "-b", project.base_branch,
            f"https://github.com/{repo['name']}.git", str(path), env=ctx.env(), timeout=600,
        )  # fmt: skip
    os.utime(path)  # in use: keep it from the sweep
    return str(path)


async def _refresh(path: Path, branch: str, env: dict[str, str]) -> bool:
    """Bring an existing checkout to the latest *branch*, dropping anything the agent left. False if there is none."""
    if not (path / ".git").exists():
        return False
    try:
        await shell.run("git", "fetch", "-q", "origin", branch, cwd=str(path), env=env, timeout=300)
        await shell.run("git", "reset", "-q", "--hard", "FETCH_HEAD", cwd=str(path), env=env)
        await shell.run("git", "clean", "-qfdx", cwd=str(path), env=env)
        return True
    except Exception:
        logger.warning("refreshing %s failed, cloning again", path, exc_info=True)
        return False


def sweep(workdir: str, max_age: float = KEEP_CHECKOUT_SECONDS) -> None:
    """Remove checkouts of chats nobody has written to for *max_age* seconds."""
    root = Path(workdir) / "chats"
    if not root.is_dir():
        return
    cutoff = time.time() - max_age
    for path in root.iterdir():
        try:
            if path.stat().st_mtime < cutoff:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass


async def _set_activity(ctx: WorkerContext, chat_id: uuid.UUID, text: str) -> None:
    async with ctx.session_factory() as session:
        chat = await session.get(Chat, chat_id)
        if chat is not None and chat.state == ChatState.ANSWERING:
            chat.activity = text[:200]
            await session.commit()


async def _requeue(ctx: WorkerContext, chat_id: uuid.UUID, activity: str) -> None:
    async with ctx.session_factory() as session:
        chat = await session.get(Chat, chat_id, with_for_update=True)
        if chat is not None:
            chat.state, chat.activity = ChatState.QUEUED, activity
            await session.commit()


async def _finish(
    ctx: WorkerContext,
    chat_id: uuid.UUID,
    seen: datetime | None,
    *,
    reply: ChatMessage | None = None,
    error: str | None = None,
    event: str | None = None,
    session_id: str | None = None,
    digest: str | None = None,
) -> None:
    """Store the turn's outcome. The chat goes back to the queue if the owner wrote meanwhile."""
    async with ctx.session_factory() as session:
        chat = await session.get(Chat, chat_id, with_for_update=True)
        if chat is None:
            return
        if reply is not None:
            session.add(reply)
        if error:
            session.add(ChatMessage(chat_id=chat_id, role="error", text=error[-2000:]))
        if event:
            session.add(ChatMessage(chat_id=chat_id, role="event", text=event))
        metadata = {k: v for k, v in (chat.metadata_ or {}).items() if k != STOP}
        if seen:
            metadata["seen"] = seen.isoformat()
        if digest:
            metadata["context_digest"] = digest
        chat.metadata_ = metadata
        chat.session_id = session_id or chat.session_id
        newer = (
            await session.execute(
                select(ChatMessage.id)
                .where(ChatMessage.chat_id == chat_id, ChatMessage.role == "user")
                .where(ChatMessage.created_at > seen if seen else true())
                .limit(1)
            )
        ).first()
        chat.state = ChatState.QUEUED if newer else ChatState.IDLE
        chat.activity = None
        chat.updated_at = datetime.now(UTC)
        await session.commit()
