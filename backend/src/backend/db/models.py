from datetime import datetime

from sqlalchemy import DateTime, Float, String, UniqueConstraint, func
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
