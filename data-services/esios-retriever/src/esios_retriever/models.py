from datetime import datetime

from pydantic import BaseModel, Field


class IndicatorSummary(BaseModel):
    """A discoverable ESIOS indicator — use EsiosClient.list_indicators() to
    find the numeric ID for whatever fundamental data you need (demand,
    generation by technology, prices, etc.).
    """

    id: int
    name: str


class IndicatorValue(BaseModel):
    """A single timestamped observation for one indicator."""

    timestamp: datetime
    value: float
    geo_id: int | None = None
    geo_name: str | None = None


class IndicatorSeries(BaseModel):
    """A time series for one ESIOS indicator."""

    indicator_id: int
    name: str = ""
    values: list[IndicatorValue] = Field(default_factory=list)
