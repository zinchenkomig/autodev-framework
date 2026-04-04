"""add ticket_number to tasks

Revision ID: h6c7d8e9f0a1
Revises: g5b6c7d8e9f0
Create Date: 2026-04-04 13:20:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "h6c7d8e9f0a1"
down_revision = "g5b6c7d8e9f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS task_ticket_seq")
    op.add_column(
        "tasks",
        sa.Column(
            "ticket_number",
            sa.Integer(),
            server_default=sa.text("nextval('task_ticket_seq')"),
            nullable=True,
        ),
    )
    # Backfill existing tasks with sequential numbers ordered by created_at
    op.execute(
        """
        UPDATE tasks SET ticket_number = sub.rn
        FROM (
            SELECT id, ROW_NUMBER() OVER (ORDER BY created_at) AS rn
            FROM tasks
        ) sub
        WHERE tasks.id = sub.id
        """
    )
    # Set sequence to continue after max
    op.execute("SELECT setval('task_ticket_seq', COALESCE((SELECT MAX(ticket_number) FROM tasks), 0))")
    # Now make it NOT NULL and unique
    op.alter_column("tasks", "ticket_number", nullable=False)
    op.create_unique_constraint("uq_tasks_ticket_number", "tasks", ["ticket_number"])
    op.create_index("ix_tasks_ticket_number", "tasks", ["ticket_number"])


def downgrade() -> None:
    op.drop_index("ix_tasks_ticket_number", table_name="tasks")
    op.drop_constraint("uq_tasks_ticket_number", "tasks")
    op.drop_column("tasks", "ticket_number")
    op.execute("DROP SEQUENCE IF EXISTS task_ticket_seq")
