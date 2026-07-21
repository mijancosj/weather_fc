"""create outage_notifications table

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outage_notifications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("resource_type", sa.String(length=16), nullable=False),
        sa.Column("business_type", sa.String(length=8), nullable=False),
        sa.Column("reason_code", sa.String(length=8), nullable=True),
        sa.Column("area", sa.String(length=64), nullable=True),
        sa.Column("in_area", sa.String(length=64), nullable=True),
        sa.Column("out_area", sa.String(length=64), nullable=True),
        sa.Column("unit_id", sa.String(length=64), nullable=True),
        sa.Column("unit_name", sa.String(length=256), nullable=True),
        sa.Column("location_name", sa.String(length=128), nullable=True),
        sa.Column("psr_type", sa.String(length=8), nullable=True),
        sa.Column("nominal_capacity_mw", sa.Float(), nullable=True),
        sa.Column("min_available_capacity_mw", sa.Float(), nullable=True),
        sa.Column("max_available_capacity_mw", sa.Float(), nullable=True),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "inserted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "event_id", "revision_number", name="uq_outage_notifications_event_revision"
        ),
    )
    op.create_index("ix_outage_notifications_event_id", "outage_notifications", ["event_id"])
    op.create_index(
        "ix_outage_notifications_resource_type", "outage_notifications", ["resource_type"]
    )
    op.create_index("ix_outage_notifications_area", "outage_notifications", ["area"])
    op.create_index(
        "ix_outage_notifications_period_start", "outage_notifications", ["period_start"]
    )
    op.create_index("ix_outage_notifications_period_end", "outage_notifications", ["period_end"])


def downgrade() -> None:
    op.drop_index("ix_outage_notifications_period_end", table_name="outage_notifications")
    op.drop_index("ix_outage_notifications_period_start", table_name="outage_notifications")
    op.drop_index("ix_outage_notifications_area", table_name="outage_notifications")
    op.drop_index("ix_outage_notifications_resource_type", table_name="outage_notifications")
    op.drop_index("ix_outage_notifications_event_id", table_name="outage_notifications")
    op.drop_table("outage_notifications")
