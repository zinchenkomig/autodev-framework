"""Project idea: what the product is for, the measure the scout and the PM hold it to

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-12 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("idea", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "idea")
