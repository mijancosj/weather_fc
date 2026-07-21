from datetime import date, datetime

from pydantic import BaseModel, Field


class MarketIndexPrice(BaseModel):
    """A single GB market index (day-ahead reference) price point.

    `start_time` is the actual UTC instant this half-hourly settlement
    period starts — use it as the timestamp, not `settlement_date` alone.
    A day has 48 settlement periods; `settlement_date` is the same for all
    of them, so using it (e.g. combined with midnight) collapses all 48
    periods onto one timestamp.
    """

    settlement_date: date
    settlement_period: int
    start_time: datetime
    price_gbp_mwh: float
    volume_mwh: float | None = None
    data_provider: str
    source: str = "elexon"


class MarketIndexPriceSeries(BaseModel):
    """A contiguous series of GB market index prices."""

    currency: str = "GBP"
    points: list[MarketIndexPrice] = Field(default_factory=list)
