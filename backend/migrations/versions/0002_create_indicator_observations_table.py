"""create indicator_observations table

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "indicator_observations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("indicator_id", sa.String(length=64), nullable=False),
        sa.Column("indicator_name", sa.String(length=256), nullable=True),
        sa.Column("geo_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("geo_name", sa.String(length=128), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column(
            "inserted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "source",
            "indicator_id",
            "geo_id",
            "timestamp",
            name="uq_indicator_observations_source_indicator_geo_timestamp",
        ),
    )
    op.create_index("ix_indicator_observations_source", "indicator_observations", ["source"])
    op.create_index(
        "ix_indicator_observations_indicator_id", "indicator_observations", ["indicator_id"]
    )
    op.create_index(
        "ix_indicator_observations_timestamp", "indicator_observations", ["timestamp"]
    )


def downgrade() -> None:
    op.drop_index("ix_indicator_observations_timestamp", table_name="indicator_observations")
    op.drop_index("ix_indicator_observations_indicator_id", table_name="indicator_observations")
    op.drop_index("ix_indicator_observations_source", table_name="indicator_observations")
    op.drop_table("indicator_observations")
