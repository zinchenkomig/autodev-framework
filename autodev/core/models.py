"""SQLAlchemy ORM models for the AutoDev Framework.

Defines persistent entities: projects, tasks, agents, logs, releases.
Uses PostgreSQL-specific types (UUID, ARRAY, JSONB) on PostgreSQL, and falls
back to JSON-serialised TEXT columns on other dialects (e.g. SQLite for tests).
"""

import enum
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, Sequence, String, Text, func
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


class TaskType(enum.StrEnum):
    """Task types that affect routing."""

    FEATURE = "feature"
    HOTFIX = "hotfix"  # bypasses release manager, goes straight to current staging


class Priority(enum.StrEnum):
    """Task priority levels."""

    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class TaskStatus(enum.StrEnum):
    """Lifecycle states of a development task.

    queued → in_progress → ci → deploying → on_stage → released
    A fix round (red CI, merge conflict, owner feedback) sends the task back
    to ``queued`` with a pending fix in ``metadata["fix"]``.
    """

    QUEUED = "queued"
    IN_PROGRESS = "in_progress"  # Claude Code is working on it
    CI = "ci"  # PR open, waiting for checks, then auto-merge into stage
    DEPLOYING = "deploying"  # merged into stage, waiting for stage to run it
    ON_STAGE = "on_stage"  # verified on stage, waiting for a prod release
    RELEASED = "released"
    FAILED = "failed"
    CANCELLED = "cancelled"


#: Statuses meaning the change is merged into the stage branch.
MERGED_STATUSES = frozenset({TaskStatus.DEPLOYING, TaskStatus.ON_STAGE, TaskStatus.RELEASED})
#: Statuses of work that is still on its way to stage.
OPEN_STATUSES = frozenset({TaskStatus.QUEUED, TaskStatus.IN_PROGRESS, TaskStatus.CI, TaskStatus.DEPLOYING})
#: Statuses a task never leaves on its own.
TERMINAL_STATUSES = frozenset({TaskStatus.RELEASED, TaskStatus.FAILED, TaskStatus.CANCELLED})


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


class ReleaseStatus(enum.StrEnum):
    """Release lifecycle states."""

    PENDING = "pending"  # stage→main PRs open, waiting for checks / merge
    DEPLOYED = "deployed"  # merged into the prod branch
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Project(Base):
    """A product the agents work on: one repo (a monorepo for several apps) and its stage."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)  # slug
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # [{"name": "owner/repo", "version_url": "...", "setup": "..."}] — exactly one entry
    repos: Mapped[list[dict]] = mapped_column(_JSONEncodedDict(), nullable=False, default=list)
    base_branch: Mapped[str] = mapped_column(String(100), nullable=False, default="stage")
    prod_branch: Mapped[str] = mapped_column(String(100), nullable=False, default="main")
    stage_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    smoke_paths: Mapped[list[str]] = mapped_column(_JSONEncodedDict(), nullable=False, default=list)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)  # extra prompt text
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)  # overrides AUTODEV_MODEL
    max_parallel: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    def repo(self, name: str | None = None) -> dict | None:
        """The project's repo entry; with *name* (full or bare), only if it is that repo."""
        if not self.repos:
            return None
        entry = self.repos[0]
        if name and name not in (entry["name"], entry["name"].split("/")[-1]):
            return None
        return entry

    def __repr__(self) -> str:
        return f"<Project id={self.id!r}>"


class Task(Base):
    """A development task assigned to an agent."""

    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(_UUID(), primary_key=True, default=uuid.uuid4)
    ticket_number: Mapped[int] = mapped_column(
        Integer,
        Sequence("task_ticket_seq"),
        unique=True,
        nullable=False,
        index=True,
        server_default=func.nextval("task_ticket_seq"),
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default=TaskSource.MANUAL)
    task_type: Mapped[str] = mapped_column(String(20), nullable=False, default=TaskType.FEATURE)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default=Priority.NORMAL)
    story_points: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=TaskStatus.QUEUED)
    assigned_to: Mapped[str | None] = mapped_column(String(100), nullable=True)
    project_id: Mapped[str | None] = mapped_column(
        String(100), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    repo: Mapped[str | None] = mapped_column(String(255), nullable=True)  # owner/name
    issue_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pr_url: Mapped[str | None] = mapped_column(String, nullable=True)
    branch: Mapped[str | None] = mapped_column(String, nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(100), nullable=True)  # Claude Code session
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # fix rounds so far
    merge_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # Claude's summary → PR body
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    release_id: Mapped[uuid.UUID | None] = mapped_column(_UUID(), nullable=True)
    depends_on: Mapped[list[uuid.UUID] | None] = mapped_column(_JSONEncodedList(), nullable=True, default=list)
    # The main task this one belongs to (follow-ups, QA fixes).
    # Always the root, so the hierarchy is one level deep.
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        _UUID(), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    metadata_: Mapped[dict | None] = mapped_column("metadata", _JSONEncodedDict(), nullable=True, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    status_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    project: Mapped[Project | None] = relationship("Project", lazy="selectin")

    @property
    def root_id(self) -> uuid.UUID:
        """Parent for a task spawned from this one."""
        return self.parent_id or self.id

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

    def __repr__(self) -> str:
        return f"<Agent id={self.id!r} role={self.role!r} status={self.status}>"


class AgentLog(Base):
    """A log entry emitted by the orchestrator during task processing."""

    __tablename__ = "agent_logs"

    id: Mapped[uuid.UUID] = mapped_column(_UUID(), primary_key=True, default=uuid.uuid4)
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


class TaskTransition(Base):
    """Records every status transition for a task."""

    __tablename__ = "task_transitions"

    id: Mapped[uuid.UUID] = mapped_column(_UUID(), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        _UUID(), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_status: Mapped[str] = mapped_column(String(30), nullable=False)
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    triggered_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    def __repr__(self) -> str:
        return f"<TaskTransition {self.from_status} → {self.to_status} task={self.task_id}>"


class Release(Base):
    """A promotion of a project's stage branch to production."""

    __tablename__ = "releases"

    id: Mapped[uuid.UUID] = mapped_column(_UUID(), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[str | None] = mapped_column(
        String(100), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default=ReleaseStatus.PENDING)
    tasks: Mapped[list[uuid.UUID]] = mapped_column(_JSONEncodedList(), nullable=False, default=list)
    release_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # [{"repo": "owner/name", "pr_number": 1, "pr_url": "...", "merged": false}]
    release_prs: Mapped[list[dict] | None] = mapped_column(_JSONEncodedDict(), nullable=True, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    production_deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    def __repr__(self) -> str:
        return f"<Release id={self.id} version={self.version!r} status={self.status}>"


class Setting(Base):
    """Key-value settings storage."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class AlertSeverity(enum.StrEnum):
    """Alert severity levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertType(enum.StrEnum):
    """Types of alerts."""

    TASK_FAILED = "task_failed"
    API_ERROR = "api_error"
    TASK_STUCK = "task_stuck"
    AGENT_STUCK = "agent_stuck"
    ORCHESTRATOR_ERROR = "orchestrator_error"
    CUSTOM = "custom"


class Alert(Base):
    """System alert for monitoring and incident tracking."""

    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(_UUID(), primary_key=True, default=uuid.uuid4)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default=AlertSeverity.MEDIUM)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)  # task_id, endpoint, etc.
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    def __repr__(self) -> str:
        return f"<Alert id={self.id} type={self.type} severity={self.severity} resolved={self.resolved}>"


class TaskArtifact(Base):
    """A file produced for a task, e.g. a stage screenshot taken by QA."""

    __tablename__ = "task_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(_UUID(), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        _UUID(), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)  # "screenshot"
    name: Mapped[str] = mapped_column(String(500), nullable=False)  # e.g. the page URL
    content_type: Mapped[str] = mapped_column(String(100), nullable=False, default="image/png")
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class ChatState(enum.StrEnum):
    """Whose turn it is in a chat."""

    IDLE = "idle"  # waiting for the owner
    QUEUED = "queued"  # the owner wrote; waiting for a free chat slot
    ANSWERING = "answering"  # the agent is on it


class Chat(Base):
    """A conversation with an agent about something: a task now, a project or anything later.

    ``subject``/``subject_id`` name what it is about (see :mod:`autodev.chats`), which decides
    the agent's context and the actions it may propose.
    """

    __tablename__ = "chats"

    id: Mapped[uuid.UUID] = mapped_column(_UUID(), primary_key=True, default=uuid.uuid4)
    subject: Mapped[str] = mapped_column(String(30), nullable=False)  # "task"
    subject_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    project_id: Mapped[str | None] = mapped_column(
        String(100), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    state: Mapped[str] = mapped_column(String(20), nullable=False, default=ChatState.IDLE)
    session_id: Mapped[str | None] = mapped_column(String(100), nullable=True)  # Claude Code session
    activity: Mapped[str | None] = mapped_column(Text, nullable=True)  # what the agent is doing right now
    # {"seen": iso time of the last message the agent took in, "context_digest": the subject's
    #  context as the agent last saw it, "stop": the owner pressed stop}
    metadata_: Mapped[dict | None] = mapped_column("metadata", _JSONEncodedDict(), nullable=True, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<Chat id={self.id} subject={self.subject}:{self.subject_id} state={self.state}>"


class ChatMessage(Base):
    """One message: the owner's question, the agent's answer, or an event (an approved action)."""

    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(_UUID(), primary_key=True, default=uuid.uuid4)
    chat_id: Mapped[uuid.UUID] = mapped_column(
        _UUID(), ForeignKey("chats.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user | assistant | event | error
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # What the owner points at, e.g. the test-plan step the question is about.
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Actions the agent proposes; each waits for the owner's approval:
    # [{"action": "follow_up", "title": ..., "description": ..., "state": "pending|applied|rejected",
    #   "result": {...}, "error": ...}]
    proposals: Mapped[list[dict] | None] = mapped_column(_JSONEncodedDict(), nullable=True, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
