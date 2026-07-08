from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db.models import PricePoint


class PriceRepository:
    """Postgres-backed store for normalized price data across all sources.

    (source, area, timestamp) is treated as a natural key: re-fetching an
    overlapping window overwrites the existing row rather than duplicating it
    (see the ON CONFLICT clause in upsert_prices, backed by the unique
    constraint on PricePoint).
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def upsert_prices(self, rows: list[dict]) -> None:
        if not rows:
            return

        async with self._session_factory() as session, session.begin():
            stmt = insert(PricePoint).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["source", "area", "timestamp"],
                set_={
                    "price_per_mwh": stmt.excluded.price_per_mwh,
                    "currency": stmt.excluded.currency,
                },
            )
            await session.execute(stmt)

    async def query(self, source: str | None = None, area: str | None = None) -> list[dict]:
        async with self._session_factory() as session:
            stmt = select(PricePoint).order_by(PricePoint.timestamp)
            if source:
                stmt = stmt.where(PricePoint.source == source)
            if area:
                stmt = stmt.where(PricePoint.area == area)

            result = await session.execute(stmt)
            return [
                {
                    "source": row.source,
                    "area": row.area,
                    "timestamp": row.timestamp.isoformat(),
                    "price_per_mwh": row.price_per_mwh,
                    "currency": row.currency,
                }
                for row in result.scalars()
            ]
