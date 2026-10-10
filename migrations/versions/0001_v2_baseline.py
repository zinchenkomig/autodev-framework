"""v2 baseline

Revision ID: 0001
Revises:
Create Date: 2026-10-10 21:59:09.810016
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import autodev.core.models

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS task_ticket_seq")
    op.create_table(
        "alerts",
        sa.Column("id", autodev.core.models._UUID(), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column("resolved", sa.Boolean(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(length=100), nullable=True),
        sa.Column("notified", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "chat_sessions",
        sa.Column("id", autodev.core.models._UUID(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "events",
        sa.Column("id", autodev.core.models._UUID(), nullable=False),
        sa.Column("type", sa.String(length=100), nullable=False),
        sa.Column("payload", autodev.core.models._JSONEncodedDict(), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "project_contexts",
        sa.Column("id", autodev.core.models._UUID(), nullable=False),
        sa.Column("repo", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("stack", sa.Text(), nullable=True),
        sa.Column("features", sa.Text(), nullable=True),
        sa.Column("architecture", sa.Text(), nullable=True),
        sa.Column("current_focus", sa.Text(), nullable=True),
        sa.Column("raw_context", sa.Text(), nullable=True),
        sa.Column("last_analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("repo"),
    )
    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("repos", autodev.core.models._JSONEncodedDict(), nullable=False),
        sa.Column("base_branch", sa.String(length=100), nullable=False),
        sa.Column("prod_branch", sa.String(length=100), nullable=False),
        sa.Column("stage_url", sa.String(length=500), nullable=True),
        sa.Column("smoke_paths", autodev.core.models._JSONEncodedDict(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("max_parallel", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "pm_chat_messages",
        sa.Column("id", autodev.core.models._UUID(), nullable=False),
        sa.Column("session_id", autodev.core.models._UUID(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("task_id", autodev.core.models._UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_sessions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "releases",
        sa.Column("id", autodev.core.models._UUID(), nullable=False),
        sa.Column("project_id", sa.String(length=100), nullable=True),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("tasks", autodev.core.models._JSONEncodedList(), nullable=False),
        sa.Column("release_notes", sa.Text(), nullable=True),
        sa.Column("release_prs", autodev.core.models._JSONEncodedDict(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column("production_deployed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_releases_project_id"), "releases", ["project_id"], unique=False)
    op.create_table(
        "tasks",
        sa.Column("id", autodev.core.models._UUID(), nullable=False),
        sa.Column("ticket_number", sa.Integer(), server_default=sa.text("nextval('task_ticket_seq')"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("task_type", sa.String(length=20), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column("story_points", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("assigned_to", sa.String(length=100), nullable=True),
        sa.Column("project_id", sa.String(length=100), nullable=True),
        sa.Column("repo", sa.String(length=255), nullable=True),
        sa.Column("issue_number", sa.Integer(), nullable=True),
        sa.Column("pr_number", sa.Integer(), nullable=True),
        sa.Column("pr_url", sa.String(), nullable=True),
        sa.Column("branch", sa.String(), nullable=True),
        sa.Column("session_id", sa.String(length=100), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("merge_sha", sa.String(length=64), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("release_id", autodev.core.models._UUID(), nullable=True),
        sa.Column("depends_on", autodev.core.models._JSONEncodedList(), nullable=True),
        sa.Column("metadata", autodev.core.models._JSONEncodedDict(), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tasks_project_id"), "tasks", ["project_id"], unique=False)
    op.create_index(op.f("ix_tasks_ticket_number"), "tasks", ["ticket_number"], unique=True)
    op.create_table(
        "agent_logs",
        sa.Column("id", autodev.core.models._UUID(), nullable=False),
        sa.Column("agent_id", sa.String(length=100), nullable=False),
        sa.Column("task_id", autodev.core.models._UUID(), nullable=True),
        sa.Column("level", sa.String(length=20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_agent_logs_agent_id"), "agent_logs", ["agent_id"], unique=False)
    op.create_table(
        "agents",
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("current_task_id", autodev.core.models._UUID(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_runs", sa.Integer(), nullable=False),
        sa.Column("total_failures", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["current_task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "task_transitions",
        sa.Column("id", autodev.core.models._UUID(), nullable=False),
        sa.Column("task_id", autodev.core.models._UUID(), nullable=False),
        sa.Column("from_status", sa.String(length=30), nullable=False),
        sa.Column("to_status", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("triggered_by", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_task_transitions_task_id"), "task_transitions", ["task_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_task_transitions_task_id"), table_name="task_transitions")
    op.drop_table("task_transitions")
    op.drop_table("agents")
    op.drop_index(op.f("ix_agent_logs_agent_id"), table_name="agent_logs")
    op.drop_table("agent_logs")
    op.drop_index(op.f("ix_tasks_ticket_number"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_project_id"), table_name="tasks")
    op.drop_table("tasks")
    op.drop_index(op.f("ix_releases_project_id"), table_name="releases")
    op.drop_table("releases")
    op.drop_table("pm_chat_messages")
    op.drop_table("settings")
    op.drop_table("projects")
    op.drop_table("project_contexts")
    op.drop_table("events")
    op.drop_table("chat_sessions")
    op.drop_table("alerts")
    op.execute("DROP SEQUENCE IF EXISTS task_ticket_seq")
