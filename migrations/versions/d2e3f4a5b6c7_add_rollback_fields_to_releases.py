"""add rollback fields to releases

Revision ID: d2e3f4a5b6c7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-18 23:30:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'd2e3f4a5b6c7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('releases', sa.Column('reverted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('releases', sa.Column('reverted_by', sa.String(), nullable=True))
    op.add_column('releases', sa.Column('previous_status', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('releases', 'previous_status')
    op.drop_column('releases', 'reverted_by')
    op.drop_column('releases', 'reverted_at')
