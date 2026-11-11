"""Task columns nothing reads any more stop being required

``task_type`` and ``story_points`` are gone from the model. A worker still running the
previous code may insert them during a rollout, so this only lifts NOT NULL; dropping
the columns (and ``issue_number``) is for a later migration.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-12 01:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("tasks", "task_type", nullable=True)
    op.alter_column("tasks", "story_points", nullable=True)


def downgrade() -> None:
    op.execute("UPDATE tasks SET task_type = 'feature' WHERE task_type IS NULL")
    op.execute("UPDATE tasks SET story_points = 1 WHERE story_points IS NULL")
    op.alter_column("tasks", "task_type", nullable=False)
    op.alter_column("tasks", "story_points", nullable=False)
