"""Tests for SQLAlchemy ORM models."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from autodev.core.models import (
    Agent,
    AgentRole,
    AgentRun,
    AgentRunStatus,
    AgentStatus,
    Base,
    Event,
    Priority,
    Release,
    ReleaseStatus,
    Task,
    TaskSource,
    TaskStatus,
)

# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestEnums:
    def test_task_status_values(self):
        assert TaskStatus.QUEUED == "queued"
        assert TaskStatus.ASSIGNED == "assigned"
        assert TaskStatus.IN_PROGRESS == "in_progress"
        assert TaskStatus.REVIEW == "review"
        assert TaskStatus.DONE == "done"
        assert TaskStatus.FAILED == "failed"

    def test_priority_values(self):
        assert Priority.CRITICAL == "critical"
        assert Priority.HIGH == "high"
        assert Priority.NORMAL == "normal"
        assert Priority.LOW == "low"

    def test_task_source_values(self):
        assert TaskSource.GITHUB_ISSUE == "github_issue"
        assert TaskSource.AGENT_CREATED == "agent_created"
        assert TaskSource.MANUAL == "manual"

    def test_agent_role_values(self):
        assert AgentRole.DEVELOPER == "developer"
        assert AgentRole.TESTER == "tester"
        assert AgentRole.BA == "ba"
        assert AgentRole.RELEASE_MANAGER == "release_manager"
        assert AgentRole.PM == "pm"

    def test_agent_status_values(self):
        assert AgentStatus.IDLE == "idle"
        assert AgentStatus.BUSY == "busy"
        assert AgentStatus.ERROR == "error"
        assert AgentStatus.OFFLINE == "offline"

    def test_agent_run_status_values(self):
        assert AgentRunStatus.RUNNING == "running"
        assert AgentRunStatus.SUCCESS == "success"
        assert AgentRunStatus.FAILED == "failed"
        assert AgentRunStatus.TIMEOUT == "timeout"

    def test_release_status_values(self):
        assert ReleaseStatus.DRAFT == "draft"
        assert ReleaseStatus.STAGING == "staging"
        assert ReleaseStatus.PENDING_APPROVAL == "pending_approval"
        assert ReleaseStatus.APPROVED == "approved"
        assert ReleaseStatus.DEPLOYED == "deployed"
        assert ReleaseStatus.FAILED == "failed"

    def test_enum_iteration(self):
        assert set(TaskStatus) == {"queued", "assigned", "in_progress", "review", "done", "failed"}
        assert set(Priority) == {"critical", "high", "normal", "low"}


# ---------------------------------------------------------------------------
# Model instantiation tests (no DB required)
# ---------------------------------------------------------------------------


class TestTaskModel:
    def test_task_default_fields(self):
        task = Task(title="Fix login bug", source=TaskSource.GITHUB_ISSUE)
        assert task.title == "Fix login bug"
        assert task.source == TaskSource.GITHUB_ISSUE
        assert task.description is None
        assert task.assigned_to is None
        assert task.issue_number is None
        assert task.pr_number is None

    def test_task_full_fields(self):
        task_id = uuid.uuid4()
        dep_id = uuid.uuid4()
        task = Task(
            id=task_id,
            title="Implement feature X",
            description="Long description",
            source=TaskSource.MANUAL,
            priority=Priority.HIGH,
            status=TaskStatus.IN_PROGRESS,
            assigned_to=AgentRole.DEVELOPER,
            repo="user/backend",
            issue_number=42,
            pr_number=99,
            depends_on=[dep_id],
            metadata_={"sprint": 3},
            created_by="pm-agent",
        )
        assert task.id == task_id
        assert task.priority == Priority.HIGH
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.depends_on == [dep_id]
        assert task.metadata_ == {"sprint": 3}
        assert task.created_by == "pm-agent"

    def test_task_repr(self):
        task = Task(title="Test task", source=TaskSource.MANUAL)
        assert "Task" in repr(task)
        assert "Test task" in repr(task)

    def test_task_tablename(self):
        assert Task.__tablename__ == "tasks"

    def test_task_has_required_columns(self):
        columns = {c.name for c in Task.__table__.columns}
        required = {
            "id",
            "title",
            "description",
            "source",
            "priority",
            "status",
            "assigned_to",
            "repo",
            "issue_number",
            "pr_number",
            "depends_on",
            "metadata",
            "created_by",
            "created_at",
            "updated_at",
        }
        assert required.issubset(columns)


class TestAgentModel:
    def test_agent_instantiation(self):
        agent = Agent(id="developer-1", role=AgentRole.DEVELOPER)
        assert agent.id == "developer-1"
        assert agent.role == AgentRole.DEVELOPER

    def test_agent_defaults(self):
        # Column defaults apply at INSERT time (DB-side), not at instantiation.
        # total_runs / total_failures have Python-level defaults of 0 when
        # the attribute is explicitly not set.
        agent = Agent(id="tester-1", role=AgentRole.TESTER)
        assert agent.current_task_id is None
        assert agent.last_run_at is None
        # status and counters may be None until flushed; setting explicitly works
        agent2 = Agent(
            id="tester-2",
            role=AgentRole.TESTER,
            status=AgentStatus.IDLE,
            total_runs=0,
            total_failures=0,
        )
        assert agent2.status == AgentStatus.IDLE
        assert agent2.total_runs == 0
        assert agent2.total_failures == 0

    def test_agent_repr(self):
        agent = Agent(id="pm-1", role=AgentRole.PM, status=AgentStatus.BUSY)
        assert "Agent" in repr(agent)
        assert "pm-1" in repr(agent)

    def test_agent_tablename(self):
        assert Agent.__tablename__ == "agents"

    def test_agent_has_required_columns(self):
        columns = {c.name for c in Agent.__table__.columns}
        required = {
            "id",
            "role",
            "status",
            "current_task_id",
            "last_run_at",
            "total_runs",
            "total_failures",
        }
        assert required.issubset(columns)


class TestEventModel:
    def test_event_instantiation(self):
        event = Event(type="task.created", payload={"task_id": "abc"})
        assert event.type == "task.created"
        assert event.payload == {"task_id": "abc"}

    def test_event_with_uuid(self):
        event_id = uuid.uuid4()
        event = Event(id=event_id, type="pr.merged", payload={}, source="github")
        assert event.id == event_id
        assert event.source == "github"

    def test_event_repr(self):
        event = Event(type="deploy.staging", payload={})
        assert "Event" in repr(event)
        assert "deploy.staging" in repr(event)

    def test_event_tablename(self):
        assert Event.__tablename__ == "events"

    def test_event_has_required_columns(self):
        columns = {c.name for c in Event.__table__.columns}
        assert {"id", "type", "payload", "source", "created_at"}.issubset(columns)


class TestAgentRunModel:
    def test_agent_run_instantiation(self):
        run = AgentRun(
            agent_id="developer-1",
            status=AgentRunStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        assert run.agent_id == "developer-1"
        assert run.status == AgentRunStatus.RUNNING

    def test_agent_run_full_fields(self):
        run_id = uuid.uuid4()
        task_id = uuid.uuid4()
        start = datetime.now(UTC)
        finish = datetime.now(UTC)
        run = AgentRun(
            id=run_id,
            agent_id="tester-1",
            task_id=task_id,
            status=AgentRunStatus.SUCCESS,
            started_at=start,
            finished_at=finish,
            result={"output": "All tests passed"},
            tokens_used=1500,
            cost_usd=Decimal("0.0045"),
        )
        assert run.id == run_id
        assert run.task_id == task_id
        assert run.tokens_used == 1500
        assert run.cost_usd == Decimal("0.0045")
        assert run.result == {"output": "All tests passed"}

    def test_agent_run_repr(self):
        run = AgentRun(agent_id="dev-1", status=AgentRunStatus.FAILED)
        assert "AgentRun" in repr(run)

    def test_agent_run_tablename(self):
        assert AgentRun.__tablename__ == "agent_runs"

    def test_agent_run_has_required_columns(self):
        columns = {c.name for c in AgentRun.__table__.columns}
        required = {
            "id",
            "agent_id",
            "task_id",
            "status",
            "started_at",
            "finished_at",
            "result",
            "tokens_used",
            "cost_usd",
        }
        assert required.issubset(columns)


class TestReleaseModel:
    def test_release_instantiation(self):
        release = Release(version="1.0.0", tasks=[])
        assert release.version == "1.0.0"
        assert release.tasks == []

    def test_release_full_fields(self):
        release_id = uuid.uuid4()
        task_ids = [uuid.uuid4(), uuid.uuid4()]
        staging_at = datetime.now(UTC)
        prod_at = datetime.now(UTC)
        approved_at = datetime.now(UTC)
        release = Release(
            id=release_id,
            version="2.3.1",
            status=ReleaseStatus.DEPLOYED,
            tasks=task_ids,
            release_notes="Fixed critical bug in auth module",
            staging_deployed_at=staging_at,
            production_deployed_at=prod_at,
            approved_by="human-reviewer",
            approved_at=approved_at,
        )
        assert release.id == release_id
        assert release.version == "2.3.1"
        assert release.status == ReleaseStatus.DEPLOYED
        assert release.tasks == task_ids
        assert release.approved_by == "human-reviewer"

    def test_release_default_status(self):
        # Column defaults apply at INSERT; set explicitly to verify enum works.
        release = Release(version="0.1.0", tasks=[], status=ReleaseStatus.DRAFT)
        assert release.status == ReleaseStatus.DRAFT

    def test_release_repr(self):
        release = Release(version="1.2.3", tasks=[])
        assert "Release" in repr(release)
        assert "1.2.3" in repr(release)

    def test_release_tablename(self):
        assert Release.__tablename__ == "releases"

    def test_release_has_required_columns(self):
        columns = {c.name for c in Release.__table__.columns}
        required = {
            "id",
            "version",
            "status",
            "tasks",
            "release_notes",
            "staging_deployed_at",
            "production_deployed_at",
            "approved_by",
            "approved_at",
            "created_at",
        }
        assert required.issubset(columns)


class TestBaseMetadata:
    def test_all_tables_registered(self):
        table_names = set(Base.metadata.tables.keys())
        assert {"tasks", "agents", "events", "agent_runs", "releases"}.issubset(table_names)

    def test_foreign_key_agent_current_task(self):
        fks = {fk.target_fullname for fk in Agent.__table__.foreign_keys}
        assert "tasks.id" in fks

    def test_foreign_key_agent_run_agent(self):
        fks = {fk.target_fullname for fk in AgentRun.__table__.foreign_keys}
        assert "agents.id" in fks

    def test_foreign_key_agent_run_task(self):
        fks = {fk.target_fullname for fk in AgentRun.__table__.foreign_keys}
        assert "tasks.id" in fks
