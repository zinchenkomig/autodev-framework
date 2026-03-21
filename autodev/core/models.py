"""SQLAlchemy ORM models for the AutoDev Framework.

Defines persistent entities: tasks, agents, events, agent_runs, releases.
Uses PostgreSQL-specific types (UUID, ARRAY, JSONB) on PostgreSQL, and falls
back to JSON-serialised TEXT columns on other dialects (e.g. SQLite for tests).
"""

import enum
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy import types as sa_types
from sqlalchemy.dialects.postgresql import ARRAY, JSONB  # used in TypeDecorators below
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# ---------------------------------------------------------------------------
# Cross-dialect type helpers
# ---------------------------------------------------------------------------


class _JSONEncodedList(sa_types.TypeDecorator):
    """Stores a list as a JSON string; uses native ARRAY(UUID) on PostgreSQL."""

    impl = sa_types.Text
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(ARRAY(PG_UUID(as_uuid=True)))
        return dialect.type_descriptor(sa_types.Text())

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return value  # pass list[UUID] directly to asyncpg
        if value is None:
            return None
        return json.dumps([str(v) for v in value])

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return value  # asyncpg returns a list already
        if value is None:
            return []
        raw = json.loads(value)
        return [uuid.UUID(v) for v in raw]


class _JSONEncodedDict(sa_types.TypeDecorator):
    """Stores a dict as a JSON string; uses native JSONB on PostgreSQL."""

    impl = sa_types.Text
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(sa_types.Text())

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return value
        if value is None:
            return None
        return json.dumps(value)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return value
        if value is None:
            return {}
        return json.loads(value)


class _UUID(sa_types.TypeDecorator):
    """Stores UUID as a native PG UUID or as a TEXT string on other dialects."""

    impl = sa_types.Text
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(sa_types.Text())

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        return str(value)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


class Base(DeclarativeBase):
    """Base class for all ORM models."""


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class TaskSource(enum.StrEnum):
    """Origin of a task."""

    GITHUB_ISSUE = "github_issue"
    AGENT_CREATED = "agent_created"
    MANUAL = "manual"


class Priority(enum.StrEnum):
    """Task priority levels."""

    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class TaskStatus(enum.StrEnum):
    """Lifecycle states of a development task."""

    QUEUED = "queued"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    READY_TO_RELEASE = "ready_to_release"
    RELEASED = "released"
    FAILED = "failed"


class AgentRole(enum.StrEnum):
    """Available agent roles in the system."""

    DEVELOPER = "developer"
    TESTER = "tester"
    BA = "ba"
    RELEASE_MANAGER = "release_manager"
    PM = "pm"


class AgentStatus(enum.StrEnum):
    """Agent availability states."""

    IDLE = "idle"
    ASSIGNED = "assigned"
    WORKING = "working"
    BUSY = "busy"
    ERROR = "error"
    OFFLINE = "offline"


class AgentRunStatus(enum.StrEnum):
    """Status of a single agent execution run."""

    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


class ReleaseStatus(enum.StrEnum):
    """Release lifecycle states."""

    DRAFT = "draft"
    STAGING = "staging"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    DEPLOYED = "deployed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REVERTED = "reverted"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Task(Base):
    """A development task assigned to an agent."""

    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        _UUID(), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default=TaskSource.MANUAL)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default=Priority.NORMAL)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=TaskStatus.QUEUED)
    assigned_to: Mapped[str | None] = mapped_column(String(100), nullable=True)
    repo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    issue_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pr_url: Mapped[str | None] = mapped_column(String, nullable=True)
    branch: Mapped[str | None] = mapped_column(String, nullable=True)
    depends_on: Mapped[list[uuid.UUID] | None] = mapped_column(
        _JSONEncodedList(), nullable=True, default=list
    )
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata", _JSONEncodedDict(), nullable=True, default=dict
    )
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationships
    agent_runs: Mapped[list["AgentRun"]] = relationship("AgentRun", back_populates="task")

    def __repr__(self) -> str:
        return f"<Task id={self.id} title={self.title!r} status={self.status}>"


class Agent(Base):
    """Represents a registered agent instance."""

    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=AgentStatus.IDLE)
    current_task_id: Mapped[uuid.UUID | None] = mapped_column(
        _UUID(), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationships
    current_task: Mapped[Task | None] = relationship("Task", foreign_keys=[current_task_id])
    agent_runs: Mapped[list["AgentRun"]] = relationship("AgentRun", back_populates="agent")

    def __repr__(self) -> str:
        return f"<Agent id={self.id!r} role={self.role!r} status={self.status}>"


class Event(Base):
    """Domain event record for the event sourcing log."""

    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(
        _UUID(), primary_key=True, default=uuid.uuid4
    )
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(_JSONEncodedDict(), nullable=False, default=dict)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    def __repr__(self) -> str:
        return f"<Event id={self.id} type={self.type!r}>"


class AgentRun(Base):
    """A single execution run of an agent on a task."""

    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        _UUID(), primary_key=True, default=uuid.uuid4
    )
    agent_id: Mapped[str | None] = mapped_column(
        String(100), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        _UUID(), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[dict | None] = mapped_column(_JSONEncodedDict(), nullable=True)
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)

    # Relationships
    agent: Mapped[Agent | None] = relationship("Agent", back_populates="agent_runs")
    task: Mapped[Task | None] = relationship("Task", back_populates="agent_runs")

    def __repr__(self) -> str:
        return f"<AgentRun id={self.id} agent_id={self.agent_id!r} status={self.status}>"


class ChatMessage(Base):
    """A message in the PM chat history."""

    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        _UUID(), primary_key=True, default=uuid.uuid4
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # 'user' | 'pm'
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    def __repr__(self) -> str:
        return f"<ChatMessage id={self.id} role={self.role!r}>"


class AgentLog(Base):
    """A log entry emitted by the orchestrator during task processing."""

    __tablename__ = "agent_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        _UUID(), primary_key=True, default=uuid.uuid4
    )
    agent_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        _UUID(), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    # level values: info | warning | error
    level: Mapped[str] = mapped_column(String(20), nullable=False, default="info")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    def __repr__(self) -> str:
        return f"<AgentLog id={self.id} agent_id={self.agent_id!r} level={self.level!r}>"


class Release(Base):
    """A software release artifact."""

    __tablename__ = "releases"

    id: Mapped[uuid.UUID] = mapped_column(
        _UUID(), primary_key=True, default=uuid.uuid4
    )
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=ReleaseStatus.DRAFT
    )
    tasks: Mapped[list[uuid.UUID]] = mapped_column(
        _JSONEncodedList(), nullable=False, default=list
    )
    release_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    staging_deployed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    production_deployed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reverted_by: Mapped[str | None] = mapped_column(String, nullable=True)
    previous_status: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    def __repr__(self) -> str:
        return f"<Release id={self.id} version={self.version!r} status={self.status}>"


class ProjectContext(Base):
    """Project context for PM agent."""

    __tablename__ = "project_contexts"

    id: Mapped[uuid.UUID] = mapped_column(
        _UUID(), primary_key=True, default=uuid.uuid4
    )
    repo: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    stack: Mapped[str | None] = mapped_column(Text, nullable=True)
    features: Mapped[str | None] = mapped_column(Text, nullable=True)
    architecture: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_focus: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_context: Mapped[str | None] = mapped_column(Text, nullable=True)  # Full analyzed context
    last_analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
