"""Chats with an agent (see :mod:`autodev.chats`): messages, stop, and approving proposed actions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autodev import chats
from autodev.api.database import get_session
from autodev.core.models import Chat, ChatMessage, ChatState

router = APIRouter()


class ChatCreate(BaseModel):
    subject: str
    subject_id: str | None = None
    # The first question: a chat is created when the owner asks, not when they open the sheet.
    text: str | None = Field(default=None, max_length=20000)
    quote: str | None = Field(default=None, max_length=4000)


class MessageCreate(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    quote: str | None = Field(default=None, max_length=4000)


class Decision(BaseModel):
    approve: bool


class ProposalResponse(BaseModel):
    action: str
    label: str  # the approve button
    title: str
    description: str
    state: str  # pending | applied | rejected
    result: dict | None  # {"task_id", "ticket_number"} once applied


class MessageResponse(BaseModel):
    id: str
    role: str  # user | assistant | event | error
    text: str
    quote: str | None
    proposals: list[ProposalResponse]
    created_at: datetime


class Outcome(BaseModel):
    """A decided proposal, for the list of chats: what the conversation came to."""

    label: str
    title: str
    state: str  # applied | rejected
    task_id: str | None
    ticket_number: int | None


class ChatResponse(BaseModel):
    id: str
    subject: str
    subject_id: str | None
    project_id: str | None
    title: str
    question: str | None  # the owner's first message: the chat's name in a list
    outcome: list[Outcome]
    pending: int  # proposals waiting for the owner
    state: str  # idle | queued | answering
    activity: str | None  # what the agent is doing right now
    stopping: bool
    messages: list[MessageResponse]
    created_at: datetime
    updated_at: datetime


def _subject(kind: str) -> chats.Subject:
    subject = chats.SUBJECTS.get(kind)
    if subject is None:
        raise HTTPException(422, f"Unknown chat subject {kind!r}")
    return subject


def _message(m: ChatMessage, subject: chats.Subject | None) -> MessageResponse:
    actions = subject.actions if subject else {}
    return MessageResponse(
        id=str(m.id),
        role=m.role,
        text=m.text,
        quote=m.quote,
        proposals=[
            ProposalResponse(
                action=p["action"],
                label=actions[p["action"]].label if p["action"] in actions else p["action"],
                title=p.get("title", ""),
                description=p.get("description", ""),
                state=p.get("state", chats.PENDING),
                result=p.get("result"),
            )
            for p in m.proposals or []
        ],
        created_at=m.created_at,
    )


async def respond(session: AsyncSession, chat: Chat) -> ChatResponse:
    rows = await session.execute(
        select(ChatMessage).where(ChatMessage.chat_id == chat.id).order_by(ChatMessage.created_at)
    )
    subject = chats.SUBJECTS.get(chat.subject)
    messages = [_message(m, subject) for m in rows.scalars()]
    proposals = [p for m in messages for p in m.proposals]
    return ChatResponse(
        id=str(chat.id),
        subject=chat.subject,
        subject_id=chat.subject_id,
        project_id=chat.project_id,
        title=chat.title,
        question=next((m.text[:300] for m in messages if m.role == "user"), None),
        outcome=[
            Outcome(
                label=p.label,
                title=p.title,
                state=p.state,
                task_id=(p.result or {}).get("task_id"),
                ticket_number=(p.result or {}).get("ticket_number"),
            )
            for p in proposals
            if p.state != chats.PENDING
        ],
        pending=sum(p.state == chats.PENDING for p in proposals),
        state=chat.state,
        activity=chat.activity,
        stopping="stop" in (chat.metadata_ or {}),
        messages=messages,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
    )


async def load_chat(session: AsyncSession, chat_id: str, *, lock: bool = False) -> Chat:
    try:
        chat = await session.get(Chat, uuid.UUID(chat_id), with_for_update=lock)
    except ValueError:
        chat = None
    if chat is None:
        raise HTTPException(404, "Chat not found")
    return chat


@router.get("/", summary="Find chats about something")
async def list_chats(
    session: Annotated[AsyncSession, Depends(get_session)],
    subject: str | None = Query(default=None),
    subject_id: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[ChatResponse]:
    stmt = select(Chat).order_by(Chat.updated_at.desc()).limit(limit)
    if subject:
        stmt = stmt.where(Chat.subject == subject)
    if subject_id:
        stmt = stmt.where(Chat.subject_id == subject_id)
    if project_id:
        stmt = stmt.where(Chat.project_id == project_id)
    return [await respond(session, c) for c in (await session.execute(stmt)).scalars()]


@router.post("/", summary="Start a chat, with its first question (for subjects with one chat: get that one)")
async def create_chat(body: ChatCreate, session: Annotated[AsyncSession, Depends(get_session)]) -> ChatResponse:
    subject = _subject(body.subject)
    if subject.single:
        existing = (
            await session.execute(
                select(Chat)
                .where(Chat.subject == body.subject, Chat.subject_id == body.subject_id)
                .limit(1)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if existing is not None:
            if body.text and body.text.strip():
                _ask(session, existing, body.text, body.quote)
                await session.flush()
            return await respond(session, existing)
    topic = await subject.topic(session, body.subject_id)
    if topic is None:
        raise HTTPException(404, "Nothing to chat about: the subject doesn't exist")
    chat = Chat(
        subject=body.subject,
        subject_id=body.subject_id,
        project_id=topic.project.id if topic.project else None,
        title=topic.title,
        state=ChatState.IDLE,
        metadata_={},
    )
    session.add(chat)
    await session.flush()
    if body.text and body.text.strip():
        _ask(session, chat, body.text, body.quote)
        await session.flush()
    return await respond(session, chat)


@router.get("/{chat_id}", summary="A chat with its messages")
async def get_chat(chat_id: str, session: Annotated[AsyncSession, Depends(get_session)]) -> ChatResponse:
    return await respond(session, await load_chat(session, chat_id))


@router.delete("/{chat_id}", summary="Delete a chat (start the conversation over)", status_code=204)
async def delete_chat(chat_id: str, session: Annotated[AsyncSession, Depends(get_session)]) -> None:
    chat = await load_chat(session, chat_id, lock=True)
    if chat.state == ChatState.ANSWERING:
        raise HTTPException(409, "The agent is answering — stop it first")
    await session.delete(chat)


@router.post("/{chat_id}/messages", summary="Write to the agent")
async def post_message(
    chat_id: str, body: MessageCreate, session: Annotated[AsyncSession, Depends(get_session)]
) -> ChatResponse:
    """Queue the message for the agent. While it is answering, the message waits for the next turn."""
    chat = await load_chat(session, chat_id, lock=True)
    if not body.text.strip():
        raise HTTPException(422, "Empty message")
    _ask(session, chat, body.text, body.quote)
    await session.flush()
    return await respond(session, chat)


def _ask(session: AsyncSession, chat: Chat, text: str, quote: str | None) -> None:
    """The owner's message, for the agent's next turn."""
    session.add(ChatMessage(chat_id=chat.id, role="user", text=text.strip(), quote=(quote or "").strip() or None))
    if chat.state == ChatState.IDLE:
        chat.state = ChatState.QUEUED
    chat.updated_at = datetime.now(UTC)


@router.post("/{chat_id}/stop", summary="Stop the agent's answer")
async def stop(chat_id: str, session: Annotated[AsyncSession, Depends(get_session)]) -> ChatResponse:
    chat = await load_chat(session, chat_id, lock=True)
    if chat.state == ChatState.QUEUED:
        # Not picked up yet: the waiting messages stay as they are, unanswered.
        chat.state, chat.activity = ChatState.IDLE, None
    elif chat.state == ChatState.ANSWERING:
        # The worker stops the session within seconds and records it.
        chat.metadata_ = {**(chat.metadata_ or {}), "stop": True}
    return await respond(session, chat)


@router.post("/{chat_id}/messages/{message_id}/proposals/{index}", summary="Approve or reject a proposed action")
async def decide(
    chat_id: str,
    message_id: str,
    index: int,
    body: Decision,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChatResponse:
    chat = await load_chat(session, chat_id, lock=True)
    try:
        message = await session.get(ChatMessage, uuid.UUID(message_id), with_for_update=True)
    except ValueError:
        message = None
    if message is None or message.chat_id != chat.id:
        raise HTTPException(404, "Message not found")
    proposals = [dict(p) for p in message.proposals or []]
    if not 0 <= index < len(proposals):
        raise HTTPException(404, "No such proposal")
    proposal = proposals[index]
    if proposal.get("state") != chats.PENDING:
        raise HTTPException(409, "Already decided")

    if body.approve:
        action = _subject(chat.subject).actions.get(proposal["action"])
        if action is None:
            raise HTTPException(409, f"Action {proposal['action']!r} is not available anymore")
        applied = await action.apply(session, chat, proposal)
        proposal.update(state=chats.APPLIED, result=applied.result)
        session.add(ChatMessage(chat_id=chat.id, role="event", text=applied.text))
    else:
        proposal["state"] = chats.REJECTED
        session.add(ChatMessage(chat_id=chat.id, role="event", text=f"Отклонено: {proposal['title']}"))
    proposals[index] = proposal
    message.proposals = proposals
    await session.flush()
    return await respond(session, chat)
