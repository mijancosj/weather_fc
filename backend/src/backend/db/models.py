from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class PricePoint(Base):
    """A single normalized price observation from any source.

    (source, area, timestamp) is the natural key — re-fetching an overlapping
    window is expected and should overwrite, not duplicate, so
    it's enforced as a unique constraint and used as the upsert conflict
    target in PriceRepository.
    """

    __tablename__ = "prices"
    __table_args__ = (
        UniqueConstraint("source", "area", "timestamp", name="uq_prices_source_area_timestamp"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    area: Mapped[str] = mapped_column(String(64), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    price_per_mwh: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8))
    inserted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IndicatorObservation(Base):
    """A single timestamped value for one indicator from one source — for
    fundamental data (demand, generation by technology, etc.) that doesn't
    fit the money-denominated `prices` table.

    (source, indicator_id, geo_id, timestamp) is the natural key. geo_id
    defaults to 0 (not NULL) for indicators with no geographic breakdown,
    since Postgres treats NULL as distinct in unique constraints — a NULL
    geo_id would silently accumulate duplicate rows on every refresh instead
    of upserting.
    """

    __tablename__ = "indicator_observations"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "indicator_id",
            "geo_id",
            "timestamp",
            name="uq_indicator_observations_source_indicator_geo_timestamp",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    indicator_id: Mapped[str] = mapped_column(String(64), index=True)
    indicator_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    geo_id: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    geo_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    inserted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OutageNotification(Base):
    """A single generation-unit or transmission-asset unavailability
    notification (REMIT-style outage) from ENTSO-E.

    Fundamentally different shape from the two tables above: not a time
    series, but a discrete, revisable event. (event_id, revision_number) is
    the natural key — outages are amended in place as their status changes
    (capacity restored, dates shifted, ...), and each revision is kept as its
    own row so the history isn't lost, rather than overwritten.

    The full per-minute capacity profile (`OutageEvent.points` on the
    retriever side) is deliberately not stored point-by-point here — for a
    trading dashboard what matters is "how much capacity is out, and for how
    long", so only the worst-case (min) and best-case (max) available
    capacity across the outage's profile are kept.
    """

    __tablename__ = "outage_notifications"
    __table_args__ = (
        UniqueConstraint(
            "event_id", "revision_number", name="uq_outage_notifications_event_revision"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), index=True)
    revision_number: Mapped[int] = mapped_column(Integer)
    resource_type: Mapped[str] = mapped_column(String(16), index=True)  # generation | transmission
    business_type: Mapped[str] = mapped_column(String(8))
    reason_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    area: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    in_area: Mapped[str | None] = mapped_column(String(64), nullable=True)
    out_area: Mapped[str | None] = mapped_column(String(64), nullable=True)
    unit_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    unit_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    location_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    psr_type: Mapped[str | None] = mapped_column(String(8), nullable=True)
    nominal_capacity_mw: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_available_capacity_mw: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_available_capacity_mw: Mapped[float | None] = mapped_column(Float, nullable=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    inserted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
