from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class AreaCode(StrEnum):
    """EIC bidding zone codes for markets currently supported.

    Extend as needed — https://transparency.entsoe.eu/content/static_content/
    Static%20content/web%20api/Guide.html#_areas lists the full set.
    """

    DE_LU = "10Y1001A1001A82H"
    FR = "10YFR-RTE------C"
    NL = "10YNL----------L"
    BE = "10YBE----------2"
    ES = "10YES-REE------0"
    GB = "10YGB----------A"


class DayAheadPrice(BaseModel):
    """A single hourly (or sub-hourly) day-ahead auction price point."""

    area: AreaCode
    timestamp: datetime
    price_eur_mwh: float
    resolution_minutes: int = 60
    source: str = "entsoe"


class DayAheadPriceSeries(BaseModel):
    """A contiguous series of day-ahead prices for one bidding zone."""

    area: AreaCode
    currency: str = "EUR"
    points: list[DayAheadPrice] = Field(default_factory=list)
