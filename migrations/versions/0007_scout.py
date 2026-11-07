"""Scout: the mode a project's scout runs in, the stage limit and its last run

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-07 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("scout", sa.String(10), nullable=False, server_default="off"))
    op.add_column("projects", sa.Column("stage_limit", sa.Integer(), nullable=False, server_default="10"))
    op.add_column("projects", sa.Column("scout_run", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "scout_run")
    op.drop_column("projects", "stage_limit")
    op.drop_column("projects", "scout")
