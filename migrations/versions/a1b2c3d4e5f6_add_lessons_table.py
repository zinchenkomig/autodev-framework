"""add lessons table

Revision ID: a1b2c3d4e5f6
Revises: b76ec2babe8c
Create Date: 2026-03-15 23:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "b76ec2babe8c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lessons",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("agent_id", sa.String(length=100), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("lesson_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_lessons_agent_id"), "lessons", ["agent_id"], unique=False)
    op.create_index(op.f("ix_lessons_created_at"), "lessons", ["created_at"], unique=False)
    op.create_index(op.f("ix_lessons_task_id"), "lessons", ["task_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_lessons_task_id"), table_name="lessons")
    op.drop_index(op.f("ix_lessons_created_at"), table_name="lessons")
    op.drop_index(op.f("ix_lessons_agent_id"), table_name="lessons")
    op.drop_table("lessons")
