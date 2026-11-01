"""PM: a project's default for thinking tasks through, and the owner's product principles

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-01 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("pm", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("projects", sa.Column("principles", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "principles")
    op.drop_column("projects", "pm")
