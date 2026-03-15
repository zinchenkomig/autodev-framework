"""SQLAlchemy ORM models for the AutoDev Framework.

Defines persistent entities: tasks, agents, events, releases, projects.

TODO: Add full field definitions and relationships for each model.
TODO: Add indexes and constraints.
TODO: Consider partitioning for large event tables.
"""

import enum
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Enum, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all ORM models."""


class TaskStatus(enum.StrEnum):
    """Lifecycle states of a development task."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    DONE = "done"
    FAILED = "failed"


class AgentRole(enum.StrEnum):
    """Available agent roles in the system."""

    DEVELOPER = "developer"
    TESTER = "tester"
    BA = "ba"
    RELEASE_MANAGER = "release_manager"
    PM = "pm"


class Task(Base):
    """A development task assigned to an agent.

    TODO: Add foreign key to Project.
    TODO: Add priority field.
    TODO: Add parent_task_id for subtask support.
    """

    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(Enum(TaskStatus), nullable=False, default=TaskStatus.PENDING)
    assigned_agent = Column(Enum(AgentRole), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    def __repr__(self) -> str:
        return f"<Task id={self.id} title={self.title!r} status={self.status}>"


class Agent(Base):
    """Represents a registered agent instance.

    TODO: Add heartbeat / last_seen tracking.
    TODO: Add capabilities field (JSON).
    """

    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    role = Column(Enum(AgentRole), nullable=False)
    name = Column(String(100), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return f"<Agent id={self.id} role={self.role} name={self.name!r}>"


class Event(Base):
    """Domain event record for the event sourcing log.

    TODO: Add payload JSON column.
    TODO: Add correlation_id for tracing.
    """

    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String(100), nullable=False)
    source = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return f"<Event id={self.id} type={self.event_type!r}>"


class Release(Base):
    """A software release artifact.

    TODO: Add changelog field.
    TODO: Add artifacts JSON list.
    """

    __tablename__ = "releases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    version = Column(String(50), nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return f"<Release id={self.id} version={self.version!r}>"
