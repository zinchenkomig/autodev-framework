"""add status_changed_at to tasks

Revision ID: g5b6c7d8e9f0
Revises: f4a5b6c7d8e9
Create Date: 2026-04-04 10:15:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "g5b6c7d8e9f0"
down_revision = "f4a5b6c7d8e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("status_changed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    # Backfill with updated_at
    op.execute("UPDATE tasks SET status_changed_at = updated_at")


def downgrade() -> None:
    op.drop_column("tasks", "status_changed_at")
