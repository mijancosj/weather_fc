from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterator
from datetime import datetime, timedelta

import httpx
import polars as pl
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from entsoe_retriever.cache import ParquetCache
from entsoe_retriever.config import EntsoeSettings, get_settings
from entsoe_retriever.exceptions import EntsoeApiError, EntsoeConfigurationError, EntsoeParseError
from entsoe_retriever.models import (
    AggregatedGenerationForecastSeries,
    AggregatedGenerationForecastValue,
    AreaCode,
    CrossBorderFlow,
    CrossBorderFlowSeries,
    DayAheadPrice,
    DayAheadPriceSeries,
    GenerationSeries,
    GenerationValue,
    InstalledCapacitySeries,
    InstalledCapacityValue,
    LoadSeries,
    LoadValue,
    OutageCapacityPoint,
    OutageEvent,
    TransferCapacity,
    TransferCapacitySeries,
)

_PRICE_NAMESPACE = {"ns": "urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3"}
_DAY_AHEAD_DOCUMENT_TYPE = "A44"  # Price document

# Actual generation, load, and wind/solar forecast all share this document
# family (and XML namespace) — confirmed against live responses, not assumed
# from the docs alone. They differ only in documentType/processType and
# whether a TimeSeries carries a MktPSRType.
_GL_NAMESPACE = {"ns": "urn:iec62325.351:tc57wg16:451-6:generationloaddocument:3:0"}
_GENERATION_DOCUMENT_TYPE = "A75"  # Actual generation per type
_GENERATION_PROCESS_TYPE = "A16"  # Realised
_LOAD_DOCUMENT_TYPE = "A65"  # Total system load
_LOAD_FORECAST_PROCESS_TYPE = "A01"  # Day-ahead forecast
_LOAD_ACTUAL_PROCESS_TYPE = "A16"  # Realised
_WIND_SOLAR_FORECAST_DOCUMENT_TYPE = "A69"  # Generation forecast for wind and solar
_WIND_SOLAR_FORECAST_PROCESS_TYPE = "A01"  # Day-ahead forecast

# Outages are a completely different response shape — confirmed live: the
# HTTP body is a ZIP archive containing one Unavailability_MarketDocument XML
# per outage notification (not one document with many TimeSeries like every
# other endpoint here).
_OUTAGE_NAMESPACE = {"ns": "urn:iec62325.351:tc57wg16:451-6:outagedocument:3:0"}
_GENERATION_OUTAGE_DOCUMENT_TYPE = "A77"  # Unavailability of generation units
_TRANSMISSION_OUTAGE_DOCUMENT_TYPE = "A78"  # Unavailability of transmission infrastructure

# Cross-border physical flows and ATC (transfer capacity) share a document
# family with day-ahead prices (Publication_MarketDocument) but confirmed
# live to use a DIFFERENT namespace version — 7:0, not 7:3 — and key each
# TimeSeries by in_Domain/out_Domain rather than a single area.
_FLOW_NAMESPACE = {"ns": "urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:0"}
_CROSS_BORDER_FLOW_DOCUMENT_TYPE = "A11"  # Aggregated energy data report (physical flows)
_TRANSFER_CAPACITY_DOCUMENT_TYPE = "A61"  # Forecasted transfer capacity (ATC)
_TRANSFER_CAPACITY_CONTRACT_TYPE = "A01"  # Daily

# Installed capacity and the aggregated (all-technology) generation forecast
# are both GL_MarketDocument family too — same namespace as generation/load —
# confirmed live.
_INSTALLED_CAPACITY_DOCUMENT_TYPE = "A68"  # Installed generation capacity per type
_INSTALLED_CAPACITY_PROCESS_TYPE = "A33"  # Year ahead
_AGGREGATED_GENERATION_FORECAST_DOCUMENT_TYPE = "A71"  # Generation forecast, all types combined
_AGGREGATED_GENERATION_FORECAST_PROCESS_TYPE = "A01"  # Day-ahead forecast

_RESOLUTION_MINUTES = {
    "PT60M": 60,
    "PT30M": 30,
    "PT15M": 15,
    "PT1M": 1,
    # Only ever seen with exactly one Point at position 1 (installed
    # capacity, one annual figure per technology) — the offset this
    # multiplies against is always 0, so the imprecision of a fixed
    # 365-day year never actually affects the computed timestamp.
    "P1Y": 365 * 24 * 60,
}


class EntsoeClient:
    """Async client for the ENTSO-E Transparency Platform REST API.

    Docs: https://transparency.entsoe.eu/content/static_content/Static%20content/web%20api/Guide.html
    """

    def __init__(self, settings: EntsoeSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self._cache = ParquetCache(self.settings.cache_dir, self.settings.cache_ttl_seconds)
        # No base_url here on purpose: httpx normalizes base_url + an empty
        # request path to end in a trailing slash, and ENTSO-E's real gateway
        # 404s on ".../api/" while accepting ".../api" — the full URL is
        # passed explicitly on each request instead (see _get).
        self._http = httpx.AsyncClient(timeout=self.settings.request_timeout_seconds)

    async def __aenter__(self) -> EntsoeClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get_day_ahead_prices(
        self,
        area: AreaCode,
        start: datetime,
        end: datetime,
        use_cache: bool = True,
    ) -> DayAheadPriceSeries:
        """Fetch day-ahead auction prices for a bidding zone over [start, end)."""
        cache_key = f"day_ahead_{area.value}_{start:%Y%m%d%H}_{end:%Y%m%d%H}"

        if use_cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return _price_series_from_frame(area, cached)

        params = {
            "documentType": _DAY_AHEAD_DOCUMENT_TYPE,
            "in_Domain": area.value,
            "out_Domain": area.value,
            "periodStart": start.strftime("%Y%m%d%H%M"),
            "periodEnd": end.strftime("%Y%m%d%H%M"),
        }
        xml_body = await self._get(params)
        series = _parse_day_ahead_xml(area, xml_body)

        if use_cache and series.points:
            self._cache.set(cache_key, _price_frame_from_series(series))

        return series

    async def get_generation_by_type(
        self,
        area: AreaCode,
        start: datetime,
        end: datetime,
        use_cache: bool = True,
    ) -> GenerationSeries:
        """Fetch actual generation per production type (wind, solar, hydro,
        nuclear, ...) for a bidding zone over [start, end) — one flat series
        spanning every production type ENTSO-E returns for the area.
        """
        cache_key = f"generation_{area.value}_{start:%Y%m%d%H}_{end:%Y%m%d%H}"

        if use_cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return _generation_series_from_frame(area, cached)

        params = {
            "documentType": _GENERATION_DOCUMENT_TYPE,
            "processType": _GENERATION_PROCESS_TYPE,
            "in_Domain": area.value,
            "periodStart": start.strftime("%Y%m%d%H%M"),
            "periodEnd": end.strftime("%Y%m%d%H%M"),
        }
        xml_body = await self._get(params)
        series = _parse_generation_xml(area, xml_body)

        if use_cache and series.points:
            self._cache.set(cache_key, _generation_frame_from_series(series))

        return series

    async def get_wind_solar_forecast(
        self,
        area: AreaCode,
        start: datetime,
        end: datetime,
        use_cache: bool = True,
    ) -> GenerationSeries:
        """Fetch the day-ahead generation forecast for wind and solar for a
        bidding zone over [start, end) — same shape as `get_generation_by_type`
        (reuses `GenerationSeries`/`GenerationValue`), just forecast instead of
        realised, and typically only psr_type B16 (Solar), B18 (Wind Offshore),
        B19 (Wind Onshore) are present. Diffing this against actual generation
        for the same window is the classic forecast-error trading signal.
        """
        cache_key = f"wind_solar_forecast_{area.value}_{start:%Y%m%d%H}_{end:%Y%m%d%H}"

        if use_cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return _generation_series_from_frame(area, cached)

        params = {
            "documentType": _WIND_SOLAR_FORECAST_DOCUMENT_TYPE,
            "processType": _WIND_SOLAR_FORECAST_PROCESS_TYPE,
            "in_Domain": area.value,
            "periodStart": start.strftime("%Y%m%d%H%M"),
            "periodEnd": end.strftime("%Y%m%d%H%M"),
        }
        xml_body = await self._get(params)
        series = _parse_generation_xml(area, xml_body)

        if use_cache and series.points:
            self._cache.set(cache_key, _generation_frame_from_series(series))

        return series

    async def get_load_forecast(
        self,
        area: AreaCode,
        start: datetime,
        end: datetime,
        use_cache: bool = True,
    ) -> LoadSeries:
        """Fetch the day-ahead total system load (demand) forecast for a
        bidding zone over [start, end). `end` can be in the future — this is
        a forecast, published a day ahead.
        """
        return await self._get_load(
            area, start, end, _LOAD_FORECAST_PROCESS_TYPE, is_forecast=True, use_cache=use_cache
        )

    async def get_load_actual(
        self,
        area: AreaCode,
        start: datetime,
        end: datetime,
        use_cache: bool = True,
    ) -> LoadSeries:
        """Fetch the realised/actual total system load (demand) for a bidding
        zone over [start, end). Diffing this against `get_load_forecast` for
        the same window is a classic demand-surprise trading signal.
        """
        return await self._get_load(
            area, start, end, _LOAD_ACTUAL_PROCESS_TYPE, is_forecast=False, use_cache=use_cache
        )

    async def _get_load(
        self,
        area: AreaCode,
        start: datetime,
        end: datetime,
        process_type: str,
        is_forecast: bool,
        use_cache: bool,
    ) -> LoadSeries:
        cache_key = (
            f"load_{'forecast' if is_forecast else 'actual'}_"
            f"{area.value}_{start:%Y%m%d%H}_{end:%Y%m%d%H}"
        )

        if use_cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return _load_series_from_frame(area, is_forecast, cached)

        params = {
            "documentType": _LOAD_DOCUMENT_TYPE,
            "processType": process_type,
            "outBiddingZone_Domain": area.value,
            "periodStart": start.strftime("%Y%m%d%H%M"),
            "periodEnd": end.strftime("%Y%m%d%H%M"),
        }
        xml_body = await self._get(params)
        series = _parse_load_xml(area, is_forecast, xml_body)

        if use_cache and series.points:
            self._cache.set(cache_key, _load_frame_from_series(series))

        return series

    async def get_generation_outages(
        self,
        area: AreaCode,
        start: datetime,
        end: datetime,
    ) -> list[OutageEvent]:
        """Fetch generation-unit unavailability notifications (planned
        maintenance + forced unavailability) for a bidding zone over
        [start, end). Deliberately not cached: outages are revised in place
        (same event_id, higher revision_number) as their status changes, and
        serving a stale revision to a trader is worse than an extra API call.
        """
        params = {
            "documentType": _GENERATION_OUTAGE_DOCUMENT_TYPE,
            "biddingZone_Domain": area.value,
            "periodStart": start.strftime("%Y%m%d%H%M"),
            "periodEnd": end.strftime("%Y%m%d%H%M"),
        }
        zip_bytes = await self._get_bytes(params)
        return _parse_outage_zip(zip_bytes, resource_type="generation")

    async def get_transmission_outages(
        self,
        area_in: AreaCode,
        area_out: AreaCode,
        start: datetime,
        end: datetime,
    ) -> list[OutageEvent]:
        """Fetch transmission-asset unavailability notifications for the
        interconnector between two bidding zones over [start, end). Not
        cached — see `get_generation_outages`.
        """
        params = {
            "documentType": _TRANSMISSION_OUTAGE_DOCUMENT_TYPE,
            "in_Domain": area_in.value,
            "out_Domain": area_out.value,
            "periodStart": start.strftime("%Y%m%d%H%M"),
            "periodEnd": end.strftime("%Y%m%d%H%M"),
        }
        zip_bytes = await self._get_bytes(params)
        return _parse_outage_zip(zip_bytes, resource_type="transmission")

    async def get_cross_border_flows(
        self,
        area_in: AreaCode,
        area_out: AreaCode,
        start: datetime,
        end: datetime,
        use_cache: bool = True,
    ) -> CrossBorderFlowSeries:
        """Fetch the actual physical energy flow across the interconnector
        between two bidding zones over [start, end).
        """
        cache_key = f"flows_{area_in.value}_{area_out.value}_{start:%Y%m%d%H}_{end:%Y%m%d%H}"

        if use_cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return _flow_series_from_frame(area_in, area_out, cached)

        params = {
            "documentType": _CROSS_BORDER_FLOW_DOCUMENT_TYPE,
            "in_Domain": area_in.value,
            "out_Domain": area_out.value,
            "periodStart": start.strftime("%Y%m%d%H%M"),
            "periodEnd": end.strftime("%Y%m%d%H%M"),
        }
        xml_body = await self._get(params)
        series = _parse_flow_xml(area_in, area_out, xml_body)

        if use_cache and series.points:
            self._cache.set(cache_key, _flow_frame_from_series(series))

        return series

    async def get_transfer_capacity(
        self,
        area_in: AreaCode,
        area_out: AreaCode,
        start: datetime,
        end: datetime,
        use_cache: bool = True,
    ) -> TransferCapacitySeries:
        """Fetch the day-ahead forecasted available transfer capacity (ATC)
        between two bidding zones over [start, end) — the commercial limit,
        not the physical flow (see `get_cross_border_flows`).
        """
        cache_key = (
            f"transfer_capacity_{area_in.value}_{area_out.value}_{start:%Y%m%d%H}_{end:%Y%m%d%H}"
        )

        if use_cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return _transfer_capacity_series_from_frame(area_in, area_out, cached)

        params = {
            "documentType": _TRANSFER_CAPACITY_DOCUMENT_TYPE,
            "contract_MarketAgreement.Type": _TRANSFER_CAPACITY_CONTRACT_TYPE,
            "in_Domain": area_in.value,
            "out_Domain": area_out.value,
            "periodStart": start.strftime("%Y%m%d%H%M"),
            "periodEnd": end.strftime("%Y%m%d%H%M"),
        }
        xml_body = await self._get(params)
        series = _parse_transfer_capacity_xml(area_in, area_out, xml_body)

        if use_cache and series.points:
            self._cache.set(cache_key, _transfer_capacity_frame_from_series(series))

        return series

    async def get_installed_capacity(
        self,
        area: AreaCode,
        year: int,
        use_cache: bool = True,
    ) -> InstalledCapacitySeries:
        """Fetch installed generation capacity per production type for a
        bidding zone, for one calendar year — a structural/annual figure
        (process A33, "year ahead"), not something that changes intraday.
        """
        cache_key = f"installed_capacity_{area.value}_{year}"

        if use_cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return _installed_capacity_series_from_frame(area, cached)

        params = {
            "documentType": _INSTALLED_CAPACITY_DOCUMENT_TYPE,
            "processType": _INSTALLED_CAPACITY_PROCESS_TYPE,
            "in_Domain": area.value,
            "periodStart": f"{year}01010000",
            "periodEnd": f"{year + 1}01010000",
        }
        xml_body = await self._get(params)
        series = _parse_installed_capacity_xml(area, xml_body)

        if use_cache and series.points:
            self._cache.set(cache_key, _installed_capacity_frame_from_series(series))

        return series

    async def get_generation_forecast_aggregated(
        self,
        area: AreaCode,
        start: datetime,
        end: datetime,
        use_cache: bool = True,
    ) -> AggregatedGenerationForecastSeries:
        """Fetch the day-ahead generation forecast aggregated across every
        technology for a bidding zone over [start, end) — pairs with
        `get_load_forecast` as a single supply-vs-demand trading signal.
        Compare `get_wind_solar_forecast` for a per-technology breakdown.
        """
        cache_key = f"generation_forecast_agg_{area.value}_{start:%Y%m%d%H}_{end:%Y%m%d%H}"

        if use_cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return _aggregated_generation_forecast_series_from_frame(area, cached)

        params = {
            "documentType": _AGGREGATED_GENERATION_FORECAST_DOCUMENT_TYPE,
            "processType": _AGGREGATED_GENERATION_FORECAST_PROCESS_TYPE,
            "in_Domain": area.value,
            "periodStart": start.strftime("%Y%m%d%H%M"),
            "periodEnd": end.strftime("%Y%m%d%H%M"),
        }
        xml_body = await self._get(params)
        series = _parse_aggregated_generation_forecast_xml(area, xml_body)

        if use_cache and series.points:
            self._cache.set(cache_key, _aggregated_generation_forecast_frame_from_series(series))

        return series

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    async def _get(self, params: dict) -> str:
        if not self.settings.api_token:
            raise EntsoeConfigurationError(
                "ENTSOE_API_TOKEN is not set. Request one at https://transparency.entsoe.eu "
                "(My Account Settings > Web API Security Token)."
            )

        response = await self._http.get(
            self.settings.base_url,
            params={"securityToken": self.settings.api_token, **params},
        )
        if response.status_code != httpx.codes.OK:
            raise EntsoeApiError(response.status_code, response.text)
        return response.text

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    async def _get_bytes(self, params: dict) -> bytes:
        """Like `_get`, but returns the raw response body — outage endpoints
        (A77/A78) reply with a ZIP archive, not XML text.
        """
        if not self.settings.api_token:
            raise EntsoeConfigurationError(
                "ENTSOE_API_TOKEN is not set. Request one at https://transparency.entsoe.eu "
                "(My Account Settings > Web API Security Token)."
            )

        response = await self._http.get(
            self.settings.base_url,
            params={"securityToken": self.settings.api_token, **params},
        )
        if response.status_code != httpx.codes.OK:
            raise EntsoeApiError(response.status_code, response.text)
        return response.content


def _parse_day_ahead_xml(area: AreaCode, xml_body: str) -> DayAheadPriceSeries:
    try:
        root = ET.fromstring(xml_body)  # noqa: S314 — trusted first-party API response
    except ET.ParseError as exc:
        raise EntsoeParseError(f"Malformed XML from ENTSO-E: {exc}") from exc

    points: list[DayAheadPrice] = []
    for timeseries in root.findall("ns:TimeSeries", _PRICE_NAMESPACE):
        period = timeseries.find("ns:Period", _PRICE_NAMESPACE)
        if period is None:
            continue

        start_text = period.findtext("ns:timeInterval/ns:start", namespaces=_PRICE_NAMESPACE)
        if start_text is None:
            continue
        period_start = datetime.strptime(start_text, "%Y-%m-%dT%H:%MZ")

        resolution_text = period.findtext("ns:resolution", namespaces=_PRICE_NAMESPACE) or "PT60M"
        resolution_minutes = _RESOLUTION_MINUTES.get(resolution_text, 60)

        for point in period.findall("ns:Point", _PRICE_NAMESPACE):
            position_text = point.findtext("ns:position", namespaces=_PRICE_NAMESPACE)
            price_text = point.findtext("ns:price.amount", namespaces=_PRICE_NAMESPACE)
            if position_text is None or price_text is None:
                continue
            timestamp = period_start + timedelta(minutes=resolution_minutes * (int(position_text) - 1))
            points.append(
                DayAheadPrice(
                    area=area,
                    timestamp=timestamp,
                    price_eur_mwh=float(price_text),
                    resolution_minutes=resolution_minutes,
                )
            )

    return DayAheadPriceSeries(area=area, points=points)


class _GlPoint:
    __slots__ = ("psr_type", "is_consumption", "timestamp", "quantity", "resolution_minutes")

    def __init__(
        self,
        psr_type: str | None,
        is_consumption: bool,
        timestamp: datetime,
        quantity: float,
        resolution_minutes: int,
    ) -> None:
        self.psr_type = psr_type
        self.is_consumption = is_consumption
        self.timestamp = timestamp
        self.quantity = quantity
        self.resolution_minutes = resolution_minutes


def _iter_gl_points(xml_body: str) -> Iterator[_GlPoint]:
    """Walk every TimeSeries -> Period -> Point in a GL_MarketDocument-shaped
    response, shared by generation-by-type, wind/solar forecast, and load —
    all three are this same document family (confirmed live), differing only
    in documentType/processType and whether MktPSRType is present.
    """
    try:
        root = ET.fromstring(xml_body)  # noqa: S314 — trusted first-party API response
    except ET.ParseError as exc:
        raise EntsoeParseError(f"Malformed XML from ENTSO-E: {exc}") from exc

    for timeseries in root.findall("ns:TimeSeries", _GL_NAMESPACE):
        psr_type = timeseries.findtext("ns:MktPSRType/ns:psrType", namespaces=_GL_NAMESPACE)

        # Storage technologies (Hydro Pumped Storage, B10) report a separate
        # TimeSeries for consumption (pumping/charging) alongside the normal
        # generation one — same psr_type, same timestamps, different values.
        # Every pure-generation technology (confirmed live: Biomass, Wind,
        # Solar, ...) tags its TimeSeries with inBiddingZone_Domain; the rare
        # second B10 entry is tagged with outBiddingZone_Domain instead —
        # that's what marks it as consumption, not the other way around.
        is_consumption = (
            timeseries.findtext("ns:outBiddingZone_Domain.mRID", namespaces=_GL_NAMESPACE)
            is not None
        )

        period = timeseries.find("ns:Period", _GL_NAMESPACE)
        if period is None:
            continue

        start_text = period.findtext("ns:timeInterval/ns:start", namespaces=_GL_NAMESPACE)
        if start_text is None:
            continue
        period_start = datetime.strptime(start_text, "%Y-%m-%dT%H:%MZ")

        resolution_text = period.findtext("ns:resolution", namespaces=_GL_NAMESPACE) or "PT60M"
        resolution_minutes = _RESOLUTION_MINUTES.get(resolution_text, 60)

        for point in period.findall("ns:Point", _GL_NAMESPACE):
            position_text = point.findtext("ns:position", namespaces=_GL_NAMESPACE)
            quantity_text = point.findtext("ns:quantity", namespaces=_GL_NAMESPACE)
            if position_text is None or quantity_text is None:
                continue
            timestamp = period_start + timedelta(minutes=resolution_minutes * (int(position_text) - 1))
            yield _GlPoint(psr_type, is_consumption, timestamp, float(quantity_text), resolution_minutes)


def _parse_generation_xml(area: AreaCode, xml_body: str) -> GenerationSeries:
    points = [
        GenerationValue(
            area=area,
            psr_type=p.psr_type,
            timestamp=p.timestamp,
            quantity_mw=p.quantity,
            resolution_minutes=p.resolution_minutes,
            is_consumption=p.is_consumption,
        )
        for p in _iter_gl_points(xml_body)
        if p.psr_type is not None
    ]
    return GenerationSeries(area=area, points=points)


def _parse_load_xml(area: AreaCode, is_forecast: bool, xml_body: str) -> LoadSeries:
    points = [
        LoadValue(
            area=area,
            timestamp=p.timestamp,
            load_mw=p.quantity,
            resolution_minutes=p.resolution_minutes,
        )
        for p in _iter_gl_points(xml_body)
    ]
    return LoadSeries(area=area, is_forecast=is_forecast, points=points)


def _iter_flow_points(xml_body: str) -> Iterator[tuple[str, str, datetime, float, int]]:
    """Walk every TimeSeries -> Period -> Point in a Publication_MarketDocument
    v7:0 response, shared by cross-border flows (A11) and ATC (A61) — both
    key each TimeSeries by in_Domain/out_Domain rather than a single area,
    confirmed live to be a distinct namespace version from the day-ahead
    price document (v7:3).
    """
    try:
        root = ET.fromstring(xml_body)  # noqa: S314 — trusted first-party API response
    except ET.ParseError as exc:
        raise EntsoeParseError(f"Malformed XML from ENTSO-E: {exc}") from exc

    for timeseries in root.findall("ns:TimeSeries", _FLOW_NAMESPACE):
        area_in = timeseries.findtext("ns:in_Domain.mRID", namespaces=_FLOW_NAMESPACE)
        area_out = timeseries.findtext("ns:out_Domain.mRID", namespaces=_FLOW_NAMESPACE)
        if area_in is None or area_out is None:
            continue

        period = timeseries.find("ns:Period", _FLOW_NAMESPACE)
        if period is None:
            continue

        start_text = period.findtext("ns:timeInterval/ns:start", namespaces=_FLOW_NAMESPACE)
        if start_text is None:
            continue
        period_start = datetime.strptime(start_text, "%Y-%m-%dT%H:%MZ")

        resolution_text = period.findtext("ns:resolution", namespaces=_FLOW_NAMESPACE) or "PT60M"
        resolution_minutes = _RESOLUTION_MINUTES.get(resolution_text, 60)

        for point in period.findall("ns:Point", _FLOW_NAMESPACE):
            position_text = point.findtext("ns:position", namespaces=_FLOW_NAMESPACE)
            quantity_text = point.findtext("ns:quantity", namespaces=_FLOW_NAMESPACE)
            if position_text is None or quantity_text is None:
                continue
            timestamp = period_start + timedelta(minutes=resolution_minutes * (int(position_text) - 1))
            yield area_in, area_out, timestamp, float(quantity_text), resolution_minutes


def _parse_flow_xml(area_in: AreaCode, area_out: AreaCode, xml_body: str) -> CrossBorderFlowSeries:
    points = [
        CrossBorderFlow(
            area_in=a_in, area_out=a_out, timestamp=ts, flow_mw=qty, resolution_minutes=res
        )
        for a_in, a_out, ts, qty, res in _iter_flow_points(xml_body)
    ]
    return CrossBorderFlowSeries(area_in=area_in.value, area_out=area_out.value, points=points)


def _parse_transfer_capacity_xml(
    area_in: AreaCode, area_out: AreaCode, xml_body: str
) -> TransferCapacitySeries:
    points = [
        TransferCapacity(
            area_in=a_in, area_out=a_out, timestamp=ts, capacity_mw=qty, resolution_minutes=res
        )
        for a_in, a_out, ts, qty, res in _iter_flow_points(xml_body)
    ]
    return TransferCapacitySeries(area_in=area_in.value, area_out=area_out.value, points=points)


def _parse_installed_capacity_xml(area: AreaCode, xml_body: str) -> InstalledCapacitySeries:
    points = [
        InstalledCapacityValue(
            area=area, psr_type=p.psr_type, year_start=p.timestamp, capacity_mw=p.quantity
        )
        for p in _iter_gl_points(xml_body)
        if p.psr_type is not None
    ]
    return InstalledCapacitySeries(area=area, points=points)


def _parse_aggregated_generation_forecast_xml(
    area: AreaCode, xml_body: str
) -> AggregatedGenerationForecastSeries:
    # A71's TimeSeries has no MktPSRType (it's an aggregate across every
    # technology) and tags itself with outBiddingZone_Domain — the same
    # attribute _iter_gl_points reads to flag "is_consumption" for storage
    # technologies elsewhere. That flag has no meaning for an aggregate
    # forecast and is deliberately not propagated onto this model.
    points = [
        AggregatedGenerationForecastValue(
            area=area,
            timestamp=p.timestamp,
            forecast_mw=p.quantity,
            resolution_minutes=p.resolution_minutes,
        )
        for p in _iter_gl_points(xml_body)
    ]
    return AggregatedGenerationForecastSeries(area=area, points=points)


def _parse_single_outage_xml(xml_body: str, resource_type: str) -> OutageEvent | None:
    """Parse one Unavailability_MarketDocument (one outage notification).

    Confirmed live: `Reason` is a sibling of `TimeSeries` at the document
    root (one reason for the whole notification), not nested inside it —
    easy to get backwards since every other document family here nests
    everything under TimeSeries.
    """
    try:
        root = ET.fromstring(xml_body)  # noqa: S314 — trusted first-party API response
    except ET.ParseError as exc:
        raise EntsoeParseError(f"Malformed outage XML from ENTSO-E: {exc}") from exc

    event_id = root.findtext("ns:mRID", namespaces=_OUTAGE_NAMESPACE)
    revision_text = root.findtext("ns:revisionNumber", namespaces=_OUTAGE_NAMESPACE)
    period_start_text = root.findtext(
        "ns:unavailability_Time_Period.timeInterval/ns:start", namespaces=_OUTAGE_NAMESPACE
    )
    period_end_text = root.findtext(
        "ns:unavailability_Time_Period.timeInterval/ns:end", namespaces=_OUTAGE_NAMESPACE
    )
    timeseries = root.find("ns:TimeSeries", _OUTAGE_NAMESPACE)
    if (
        event_id is None
        or revision_text is None
        or period_start_text is None
        or period_end_text is None
        or timeseries is None
    ):
        return None

    business_type = timeseries.findtext("ns:businessType", namespaces=_OUTAGE_NAMESPACE) or ""
    reason_code = root.findtext("ns:Reason/ns:code", namespaces=_OUTAGE_NAMESPACE)

    nominal_capacity_text = timeseries.findtext(
        "ns:production_RegisteredResource.pSRType.powerSystemResources.nominalP",
        namespaces=_OUTAGE_NAMESPACE,
    )

    points: list[OutageCapacityPoint] = []
    available_period = timeseries.find("ns:Available_Period", _OUTAGE_NAMESPACE)
    if available_period is not None:
        available_start_text = available_period.findtext(
            "ns:timeInterval/ns:start", namespaces=_OUTAGE_NAMESPACE
        )
        resolution_text = available_period.findtext("ns:resolution", namespaces=_OUTAGE_NAMESPACE) or "PT1M"
        resolution_minutes = _RESOLUTION_MINUTES.get(resolution_text, 1)
        if available_start_text is not None:
            available_start = datetime.strptime(available_start_text, "%Y-%m-%dT%H:%MZ")
            for point in available_period.findall("ns:Point", _OUTAGE_NAMESPACE):
                position_text = point.findtext("ns:position", namespaces=_OUTAGE_NAMESPACE)
                quantity_text = point.findtext("ns:quantity", namespaces=_OUTAGE_NAMESPACE)
                if position_text is None or quantity_text is None:
                    continue
                timestamp = available_start + timedelta(
                    minutes=resolution_minutes * (int(position_text) - 1)
                )
                points.append(
                    OutageCapacityPoint(timestamp=timestamp, available_capacity_mw=float(quantity_text))
                )

    return OutageEvent(
        event_id=event_id,
        revision_number=int(revision_text),
        resource_type=resource_type,
        business_type=business_type,
        reason_code=reason_code,
        area=timeseries.findtext("ns:biddingZone_Domain.mRID", namespaces=_OUTAGE_NAMESPACE),
        in_area=timeseries.findtext("ns:in_Domain.mRID", namespaces=_OUTAGE_NAMESPACE),
        out_area=timeseries.findtext("ns:out_Domain.mRID", namespaces=_OUTAGE_NAMESPACE),
        unit_id=timeseries.findtext(
            "ns:production_RegisteredResource.mRID", namespaces=_OUTAGE_NAMESPACE
        ),
        unit_name=timeseries.findtext(
            "ns:production_RegisteredResource.name", namespaces=_OUTAGE_NAMESPACE
        ),
        location_name=timeseries.findtext(
            "ns:production_RegisteredResource.location.name", namespaces=_OUTAGE_NAMESPACE
        ),
        psr_type=timeseries.findtext(
            "ns:production_RegisteredResource.pSRType.psrType", namespaces=_OUTAGE_NAMESPACE
        ),
        nominal_capacity_mw=float(nominal_capacity_text) if nominal_capacity_text is not None else None,
        period_start=datetime.strptime(period_start_text, "%Y-%m-%dT%H:%MZ"),
        period_end=datetime.strptime(period_end_text, "%Y-%m-%dT%H:%MZ"),
        points=points,
    )


def _parse_outage_zip(zip_bytes: bytes, resource_type: str) -> list[OutageEvent]:
    """Unzip an A77/A78 response and parse each inner document.

    Confirmed live: when there are no outages in the requested window,
    ENTSO-E returns a plain Acknowledgement_MarketDocument XML instead of a
    ZIP (same "no matching data" shape used by every other endpoint here) —
    that's not an error, just an empty result.
    """
    if zip_bytes[:2] != b"PK":
        body = zip_bytes.decode("utf-8", errors="replace")
        if "Acknowledgement_MarketDocument" in body:
            return []
        raise EntsoeParseError(f"Unexpected outage response (not a ZIP): {body[:300]}")

    events: list[OutageEvent] = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for name in zf.namelist():
            xml_body = zf.read(name).decode("utf-8")
            event = _parse_single_outage_xml(xml_body, resource_type)
            if event is not None:
                events.append(event)
    return events


def _price_frame_from_series(series: DayAheadPriceSeries) -> pl.DataFrame:
    return pl.DataFrame([point.model_dump(mode="json") for point in series.points])


def _price_series_from_frame(area: AreaCode, frame: pl.DataFrame) -> DayAheadPriceSeries:
    points = [DayAheadPrice(**row) for row in frame.to_dicts()]
    return DayAheadPriceSeries(area=area, points=points)


def _generation_frame_from_series(series: GenerationSeries) -> pl.DataFrame:
    return pl.DataFrame([point.model_dump(mode="json") for point in series.points])


def _generation_series_from_frame(area: AreaCode, frame: pl.DataFrame) -> GenerationSeries:
    points = [GenerationValue(**row) for row in frame.to_dicts()]
    return GenerationSeries(area=area, points=points)


def _load_frame_from_series(series: LoadSeries) -> pl.DataFrame:
    return pl.DataFrame([point.model_dump(mode="json") for point in series.points])


def _load_series_from_frame(area: AreaCode, is_forecast: bool, frame: pl.DataFrame) -> LoadSeries:
    points = [LoadValue(**row) for row in frame.to_dicts()]
    return LoadSeries(area=area, is_forecast=is_forecast, points=points)


def _flow_frame_from_series(series: CrossBorderFlowSeries) -> pl.DataFrame:
    return pl.DataFrame([point.model_dump(mode="json") for point in series.points])


def _flow_series_from_frame(
    area_in: AreaCode, area_out: AreaCode, frame: pl.DataFrame
) -> CrossBorderFlowSeries:
    points = [CrossBorderFlow(**row) for row in frame.to_dicts()]
    return CrossBorderFlowSeries(area_in=area_in.value, area_out=area_out.value, points=points)


def _transfer_capacity_frame_from_series(series: TransferCapacitySeries) -> pl.DataFrame:
    return pl.DataFrame([point.model_dump(mode="json") for point in series.points])


def _transfer_capacity_series_from_frame(
    area_in: AreaCode, area_out: AreaCode, frame: pl.DataFrame
) -> TransferCapacitySeries:
    points = [TransferCapacity(**row) for row in frame.to_dicts()]
    return TransferCapacitySeries(area_in=area_in.value, area_out=area_out.value, points=points)


def _installed_capacity_frame_from_series(series: InstalledCapacitySeries) -> pl.DataFrame:
    return pl.DataFrame([point.model_dump(mode="json") for point in series.points])


def _installed_capacity_series_from_frame(
    area: AreaCode, frame: pl.DataFrame
) -> InstalledCapacitySeries:
    points = [InstalledCapacityValue(**row) for row in frame.to_dicts()]
    return InstalledCapacitySeries(area=area, points=points)


def _aggregated_generation_forecast_frame_from_series(
    series: AggregatedGenerationForecastSeries,
) -> pl.DataFrame:
    return pl.DataFrame([point.model_dump(mode="json") for point in series.points])


def _aggregated_generation_forecast_series_from_frame(
    area: AreaCode, frame: pl.DataFrame
) -> AggregatedGenerationForecastSeries:
    points = [AggregatedGenerationForecastValue(**row) for row in frame.to_dicts()]
    return AggregatedGenerationForecastSeries(area=area, points=points)
