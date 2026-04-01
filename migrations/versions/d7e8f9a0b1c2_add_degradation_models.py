"""add degradation models

Revision ID: d7e8f9a0b1c2
Revises: c1d2e3f4a5b6
Create Date: 2026-03-24 13:55:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d7e8f9a0b1c2"
down_revision: str | None = "c1d2e3f4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create degradation models tables."""

    # Create degradation_configs table
    op.create_table(
        "degradation_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("target_database", sa.String(length=255), nullable=False),
        sa.Column("target_table", sa.String(length=255), nullable=False),
        sa.Column("target_columns", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=False),
        sa.Column("degradation_type", sa.String(length=50), nullable=False),
        sa.Column("degradation_mode", sa.String(length=50), nullable=False),
        sa.Column("severity", sa.Numeric(precision=3, scale=2), nullable=False),
        sa.Column("time_column", sa.String(length=255), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create degradation_operations table
    op.create_table(
        "degradation_operations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("config_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("records_affected", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("execution_details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("performed_by", sa.String(length=100), nullable=False),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["config_id"], ["degradation_configs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create degradation_backups table
    op.create_table(
        "degradation_backups",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("table_name", sa.String(length=255), nullable=False),
        sa.Column("record_id", sa.String(length=255), nullable=False),
        sa.Column("column_name", sa.String(length=255), nullable=False),
        sa.Column("original_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("data_type", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["operation_id"], ["degradation_operations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Add indexes for performance
    op.create_index("ix_degradation_configs_created_by", "degradation_configs", ["created_by"])
    op.create_index("ix_degradation_configs_target_database", "degradation_configs", ["target_database"])
    op.create_index("ix_degradation_configs_target_table", "degradation_configs", ["target_table"])

    op.create_index("ix_degradation_operations_config_id", "degradation_operations", ["config_id"])
    op.create_index("ix_degradation_operations_status", "degradation_operations", ["status"])
    op.create_index("ix_degradation_operations_performed_at", "degradation_operations", ["performed_at"])
    op.create_index("ix_degradation_operations_performed_by", "degradation_operations", ["performed_by"])

    op.create_index("ix_degradation_backups_operation_id", "degradation_backups", ["operation_id"])
    op.create_index("ix_degradation_backups_table_record", "degradation_backups", ["table_name", "record_id"])


def downgrade() -> None:
    """Drop degradation models tables."""

    # Drop indexes
    op.drop_index("ix_degradation_backups_table_record", table_name="degradation_backups")
    op.drop_index("ix_degradation_backups_operation_id", table_name="degradation_backups")
    op.drop_index("ix_degradation_operations_performed_by", table_name="degradation_operations")
    op.drop_index("ix_degradation_operations_performed_at", table_name="degradation_operations")
    op.drop_index("ix_degradation_operations_status", table_name="degradation_operations")
    op.drop_index("ix_degradation_operations_config_id", table_name="degradation_operations")
    op.drop_index("ix_degradation_configs_target_table", table_name="degradation_configs")
    op.drop_index("ix_degradation_configs_target_database", table_name="degradation_configs")
    op.drop_index("ix_degradation_configs_created_by", table_name="degradation_configs")

    # Drop tables in reverse order due to foreign key constraints
    op.drop_table("degradation_backups")
    op.drop_table("degradation_operations")
    op.drop_table("degradation_configs")