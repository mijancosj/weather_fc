"""create prices table

Revision ID: 0001
Revises:
Create Date: 2026-07-07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prices",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("area", sa.String(length=64), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price_per_mwh", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column(
            "inserted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("source", "area", "timestamp", name="uq_prices_source_area_timestamp"),
    )
    op.create_index("ix_prices_source", "prices", ["source"])
    op.create_index("ix_prices_area", "prices", ["area"])
    op.create_index("ix_prices_timestamp", "prices", ["timestamp"])


def downgrade() -> None:
    op.drop_index("ix_prices_timestamp", table_name="prices")
    op.drop_index("ix_prices_area", table_name="prices")
    op.drop_index("ix_prices_source", table_name="prices")
    op.drop_table("prices")
