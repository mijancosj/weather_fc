from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db.models import IndicatorObservation, OutageNotification, PricePoint


def _dedupe_last(rows: list[dict], key_fields: tuple[str, ...]) -> list[dict]:
    """Keep only the last row per natural key.

    A single multi-row `INSERT ... ON CONFLICT DO UPDATE` fails outright in
    Postgres (`CardinalityViolationError`) if two rows in the same statement
    target the same conflict key — this actually happened with ENTSO-E's
    generation feed (Hydro Pumped Storage reports generation and consumption
    as separate series that, before that distinction was modeled, collided
    on the same key). Deduping here is a safety net for any source, not a
    fix for one — the real fix is giving each row a genuinely unique key
    upstream; this just stops it from becoming a hard crash if that ever
    isn't quite true.
    """
    deduped = {tuple(row[field] for field in key_fields): row for row in rows}
    return list(deduped.values())


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
        rows = _dedupe_last(rows, ("source", "area", "timestamp"))

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


class IndicatorRepository:
    """Postgres-backed store for generic indicator time series (demand,
    generation by technology, or anything from any source that doesn't fit
    the money-denominated `prices` table).

    (source, indicator_id, geo_id, timestamp) is treated as a natural key —
    same re-fetch-overwrites semantics as PriceRepository.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def upsert_observations(self, rows: list[dict]) -> None:
        if not rows:
            return
        rows = _dedupe_last(rows, ("source", "indicator_id", "geo_id", "timestamp"))

        async with self._session_factory() as session, session.begin():
            stmt = insert(IndicatorObservation).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["source", "indicator_id", "geo_id", "timestamp"],
                set_={
                    "value": stmt.excluded.value,
                    "indicator_name": stmt.excluded.indicator_name,
                    "geo_name": stmt.excluded.geo_name,
                    "unit": stmt.excluded.unit,
                },
            )
            await session.execute(stmt)

    async def query(
        self,
        source: str | None = None,
        indicator_id: str | None = None,
        geo_name: str | None = None,
    ) -> list[dict]:
        async with self._session_factory() as session:
            stmt = select(IndicatorObservation).order_by(IndicatorObservation.timestamp)
            if source:
                stmt = stmt.where(IndicatorObservation.source == source)
            if indicator_id:
                stmt = stmt.where(IndicatorObservation.indicator_id == indicator_id)
            if geo_name:
                stmt = stmt.where(IndicatorObservation.geo_name == geo_name)

            result = await session.execute(stmt)
            return [
                {
                    "source": row.source,
                    "indicator_id": row.indicator_id,
                    "indicator_name": row.indicator_name,
                    "geo_id": row.geo_id,
                    "geo_name": row.geo_name,
                    "timestamp": row.timestamp.isoformat(),
                    "value": row.value,
                    "unit": row.unit,
                }
                for row in result.scalars()
            ]


class OutageRepository:
    """Postgres-backed store for ENTSO-E outage notifications
    (generation-unit and transmission-asset unavailability).

    (event_id, revision_number) is the natural key — each revision of an
    outage is kept as its own row rather than overwritten, since the
    revision history itself is meaningful (e.g. "this outage was announced,
    then extended twice").
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def upsert_outages(self, rows: list[dict]) -> None:
        if not rows:
            return
        rows = _dedupe_last(rows, ("event_id", "revision_number"))

        async with self._session_factory() as session, session.begin():
            stmt = insert(OutageNotification).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["event_id", "revision_number"],
                set_={
                    "resource_type": stmt.excluded.resource_type,
                    "business_type": stmt.excluded.business_type,
                    "reason_code": stmt.excluded.reason_code,
                    "area": stmt.excluded.area,
                    "in_area": stmt.excluded.in_area,
                    "out_area": stmt.excluded.out_area,
                    "unit_id": stmt.excluded.unit_id,
                    "unit_name": stmt.excluded.unit_name,
                    "location_name": stmt.excluded.location_name,
                    "psr_type": stmt.excluded.psr_type,
                    "nominal_capacity_mw": stmt.excluded.nominal_capacity_mw,
                    "min_available_capacity_mw": stmt.excluded.min_available_capacity_mw,
                    "max_available_capacity_mw": stmt.excluded.max_available_capacity_mw,
                    "period_start": stmt.excluded.period_start,
                    "period_end": stmt.excluded.period_end,
                },
            )
            await session.execute(stmt)

    async def query(
        self,
        resource_type: str | None = None,
        area: str | None = None,
        active_at: datetime | None = None,
        latest_revision_only: bool = True,
    ) -> list[dict]:
        """List outage notifications, most recent period first.

        `latest_revision_only` collapses each event_id down to its highest
        revision_number — what you almost always want, since older revisions
        are superseded, not additional outages. `active_at`, if given,
        filters to outages whose declared period covers that instant
        (period_start <= active_at <= period_end).
        """
        async with self._session_factory() as session:
            stmt = select(OutageNotification)
            if resource_type:
                stmt = stmt.where(OutageNotification.resource_type == resource_type)
            if area:
                stmt = stmt.where(
                    (OutageNotification.area == area)
                    | (OutageNotification.in_area == area)
                    | (OutageNotification.out_area == area)
                )
            if active_at:
                stmt = stmt.where(
                    OutageNotification.period_start <= active_at,
                    OutageNotification.period_end >= active_at,
                )
            stmt = stmt.order_by(
                OutageNotification.event_id, OutageNotification.revision_number.desc()
            )

            result = await session.execute(stmt)
            rows = list(result.scalars())

            if latest_revision_only:
                seen: set[str] = set()
                deduped = []
                for row in rows:
                    if row.event_id in seen:
                        continue
                    seen.add(row.event_id)
                    deduped.append(row)
                rows = deduped

            rows.sort(key=lambda row: row.period_start, reverse=True)

            return [
                {
                    "event_id": row.event_id,
                    "revision_number": row.revision_number,
                    "resource_type": row.resource_type,
                    "business_type": row.business_type,
                    "reason_code": row.reason_code,
                    "area": row.area,
                    "in_area": row.in_area,
                    "out_area": row.out_area,
                    "unit_id": row.unit_id,
                    "unit_name": row.unit_name,
                    "location_name": row.location_name,
                    "psr_type": row.psr_type,
                    "nominal_capacity_mw": row.nominal_capacity_mw,
                    "min_available_capacity_mw": row.min_available_capacity_mw,
                    "max_available_capacity_mw": row.max_available_capacity_mw,
                    "period_start": row.period_start.isoformat(),
                    "period_end": row.period_end.isoformat(),
                }
                for row in rows
            ]
