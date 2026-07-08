from datetime import date

from pydantic import BaseModel, Field


class MarketIndexPrice(BaseModel):
    """A single GB market index (day-ahead reference) price point."""

    settlement_date: date
    settlement_period: int
    price_gbp_mwh: float
    volume_mwh: float | None = None
    data_provider: str
    source: str = "elexon"


class MarketIndexPriceSeries(BaseModel):
    """A contiguous series of GB market index prices."""

    currency: str = "GBP"
    points: list[MarketIndexPrice] = Field(default_factory=list)
