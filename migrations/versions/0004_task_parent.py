"""task parent: follow-ups and parts hang under their main task

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-12 22:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import autodev.core.models

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Tasks spawned from another one before parent_id existed; their first dependency is the source.
_SPAWNED_BY = ("feedback", "triage", "qa", "developer")


def upgrade() -> None:
    op.add_column("tasks", sa.Column("parent_id", autodev.core.models._UUID(), nullable=True))
    op.create_index(op.f("ix_tasks_parent_id"), "tasks", ["parent_id"], unique=False)
    op.create_foreign_key("fk_tasks_parent_id", "tasks", "tasks", ["parent_id"], ["id"], ondelete="SET NULL")

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, created_by, depends_on FROM tasks ORDER BY ticket_number")).all()
    root: dict = {}
    for task_id, created_by, deps in rows:
        source = deps[0] if created_by in _SPAWNED_BY and deps and deps[0] in root else None
        root[task_id] = (root.get(source) or source) if source else None
        if root[task_id]:
            conn.execute(sa.text("UPDATE tasks SET parent_id = :p WHERE id = :id"), {"p": root[task_id], "id": task_id})


def downgrade() -> None:
    op.drop_constraint("fk_tasks_parent_id", "tasks", type_="foreignkey")
    op.drop_index(op.f("ix_tasks_parent_id"), table_name="tasks")
    op.drop_column("tasks", "parent_id")
