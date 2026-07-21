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
    PT = "10YPT-REN------W"


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


# ENTSO-E's production source register (generation technology) codes —
# https://transparency.entsoe.eu/content/static_content/Static%20content/web%20api/Guide.html#_psr_type
# Kept as a plain str->name mapping rather than a strict enum so parsing
# doesn't break if ENTSO-E returns a code not listed here; unknown codes are
# still parsed, just without a friendly name.
PSR_TYPE_NAMES: dict[str, str] = {
    "B01": "Biomass",
    "B02": "Fossil Brown coal/Lignite",
    "B03": "Fossil Coal-derived gas",
    "B04": "Fossil Gas",
    "B05": "Fossil Hard coal",
    "B06": "Fossil Oil",
    "B07": "Fossil Oil shale",
    "B08": "Fossil Peat",
    "B09": "Geothermal",
    "B10": "Hydro Pumped Storage",
    "B11": "Hydro Run-of-river and poundage",
    "B12": "Hydro Water Reservoir",
    "B13": "Marine",
    "B14": "Nuclear",
    "B15": "Other renewable",
    "B16": "Solar",
    "B17": "Waste",
    "B18": "Wind Offshore",
    "B19": "Wind Onshore",
    "B20": "Other",
    "B25": "Energy storage",
}


class GenerationValue(BaseModel):
    """A single timestamped generation quantity for one production type.

    Storage technologies (notably Hydro Pumped Storage, B10) report two
    separate series per timestamp: energy generated (discharging) and energy
    consumed (pumping/charging) — confirmed against a live response, where
    B10 appears twice with different bidding-zone-direction attributes.
    `is_consumption` distinguishes them; every other production type is
    generation-only and always has `is_consumption=False`.
    """

    area: AreaCode
    psr_type: str
    timestamp: datetime
    quantity_mw: float
    resolution_minutes: int = 60
    is_consumption: bool = False


class LoadValue(BaseModel):
    """A single timestamped total system load (demand) quantity — either the
    day-ahead forecast or the realised/actual figure, per `LoadSeries.is_forecast`.
    """

    area: AreaCode
    timestamp: datetime
    load_mw: float
    resolution_minutes: int = 60


class LoadSeries(BaseModel):
    """Total system load for one bidding zone — forecast or actual, per `is_forecast`."""

    area: AreaCode
    is_forecast: bool
    points: list[LoadValue] = Field(default_factory=list)


class GenerationSeries(BaseModel):
    """Actual generation per production type (wind, solar, hydro, ...) for
    one bidding zone — one flat list of points spanning every production
    type ENTSO-E returned; filter by `psr_type` as needed.
    """

    area: AreaCode
    points: list[GenerationValue] = Field(default_factory=list)


OUTAGE_BUSINESS_TYPE_NAMES: dict[str, str] = {
    "A53": "Planned maintenance",
    "A54": "Forced unavailability",
}


class OutageCapacityPoint(BaseModel):
    """One point in an outage's available-capacity profile. Usually just one
    flat value for the whole outage, but transmission outages can step
    (e.g. partial capacity restored partway through) — confirmed live.
    """

    timestamp: datetime
    available_capacity_mw: float


class OutageEvent(BaseModel):
    """A single generation-unit or transmission-asset unavailability
    notification (REMIT-style outage) — confirmed live to be a fundamentally
    different shape than prices/generation/load: not a uniform time series,
    but a discrete event with its own declared period and capacity profile,
    identified by `event_id` and revisable (same `event_id`, higher
    `revision_number`) as the outage's status changes.
    """

    event_id: str
    revision_number: int
    resource_type: str  # "generation" | "transmission"
    business_type: str  # raw code — see OUTAGE_BUSINESS_TYPE_NAMES
    reason_code: str | None = None
    area: str | None = None  # biddingZone, generation outages only
    in_area: str | None = None  # transmission outages only
    out_area: str | None = None  # transmission outages only
    unit_id: str | None = None
    unit_name: str | None = None
    location_name: str | None = None
    psr_type: str | None = None
    nominal_capacity_mw: float | None = None
    period_start: datetime
    period_end: datetime
    points: list[OutageCapacityPoint] = Field(default_factory=list)


class CrossBorderFlow(BaseModel):
    """A single physical energy flow measurement between two bidding zones
    (document A11) — what actually moved across the interconnector, not a
    forecast or a limit.
    """

    area_in: str
    area_out: str
    timestamp: datetime
    flow_mw: float
    resolution_minutes: int = 60


class CrossBorderFlowSeries(BaseModel):
    area_in: str
    area_out: str
    points: list[CrossBorderFlow] = Field(default_factory=list)


class TransferCapacity(BaseModel):
    """A single available transfer capacity (ATC) value between two bidding
    zones (document A61) — the day-ahead forecasted commercial capacity
    limit, not the physical flow itself. Confirmed live: points can be
    sparse (position gaps) — the value holds until the next explicit point,
    the same convention as `OutageCapacityPoint`.
    """

    area_in: str
    area_out: str
    timestamp: datetime
    capacity_mw: float
    resolution_minutes: int = 60


class TransferCapacitySeries(BaseModel):
    area_in: str
    area_out: str
    points: list[TransferCapacity] = Field(default_factory=list)


class InstalledCapacityValue(BaseModel):
    """Installed generation capacity for one production type in one bidding
    zone, for one year (document A68, process A33 = year-ahead forecast).
    Structural/annual context, not something that changes intraday — pairs
    with `GenerationValue` (actual output) to show headroom per technology.
    """

    area: AreaCode
    psr_type: str
    year_start: datetime
    capacity_mw: float


class InstalledCapacitySeries(BaseModel):
    area: AreaCode
    points: list[InstalledCapacityValue] = Field(default_factory=list)


class AggregatedGenerationForecastValue(BaseModel):
    """Total day-ahead generation forecast across every technology combined
    for one bidding zone (document A71) — not broken down by psr_type
    (compare `GenerationSeries`/`get_wind_solar_forecast`, which are
    per-technology). Pairs with `get_load_forecast` as a single supply-vs-
    demand trading signal.
    """

    area: AreaCode
    timestamp: datetime
    forecast_mw: float
    resolution_minutes: int = 60


class AggregatedGenerationForecastSeries(BaseModel):
    area: AreaCode
    points: list[AggregatedGenerationForecastValue] = Field(default_factory=list)
