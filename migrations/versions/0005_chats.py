"""chats: conversations with an agent about a task (and later other things)

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-31 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import autodev.core.models

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chats",
        sa.Column("id", autodev.core.models._UUID(), nullable=False),
        sa.Column("subject", sa.String(length=30), nullable=False),
        sa.Column("subject_id", sa.String(length=100), nullable=True),
        sa.Column("project_id", sa.String(length=100), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("session_id", sa.String(length=100), nullable=True),
        sa.Column("activity", sa.Text(), nullable=True),
        sa.Column("metadata", autodev.core.models._JSONEncodedDict(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_chats_subject_id"), "chats", ["subject_id"], unique=False)
    op.create_index(op.f("ix_chats_project_id"), "chats", ["project_id"], unique=False)
    op.create_table(
        "chat_messages",
        sa.Column("id", autodev.core.models._UUID(), nullable=False),
        sa.Column("chat_id", autodev.core.models._UUID(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column("proposals", autodev.core.models._JSONEncodedDict(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_chat_messages_chat_id"), "chat_messages", ["chat_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_chat_messages_chat_id"), table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index(op.f("ix_chats_project_id"), table_name="chats")
    op.drop_index(op.f("ix_chats_subject_id"), table_name="chats")
    op.drop_table("chats")
