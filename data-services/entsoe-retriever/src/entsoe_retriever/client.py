from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import httpx
import polars as pl
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from entsoe_retriever.cache import ParquetCache
from entsoe_retriever.config import EntsoeSettings, get_settings
from entsoe_retriever.exceptions import EntsoeApiError, EntsoeConfigurationError, EntsoeParseError
from entsoe_retriever.models import AreaCode, DayAheadPrice, DayAheadPriceSeries

_NAMESPACE = {"ns": "urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3"}
_DAY_AHEAD_DOCUMENT_TYPE = "A44"  # Price document
_RESOLUTION_MINUTES = {"PT60M": 60, "PT30M": 30, "PT15M": 15}


class EntsoeClient:
    """Async client for the ENTSO-E Transparency Platform REST API.

    Docs: https://transparency.entsoe.eu/content/static_content/Static%20content/web%20api/Guide.html
    """

    def __init__(self, settings: EntsoeSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self._cache = ParquetCache(self.settings.cache_dir, self.settings.cache_ttl_seconds)
        self._http = httpx.AsyncClient(
            base_url=self.settings.base_url,
            timeout=self.settings.request_timeout_seconds,
        )

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
                return _series_from_frame(area, cached)

        xml_body = await self._fetch_document(area, start, end)
        series = _parse_day_ahead_xml(area, xml_body)

        if use_cache and series.points:
            self._cache.set(cache_key, _frame_from_series(series))

        return series

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    async def _fetch_document(self, area: AreaCode, start: datetime, end: datetime) -> str:
        if not self.settings.api_token:
            raise EntsoeConfigurationError(
                "ENTSOE_API_TOKEN is not set. Request one at https://transparency.entsoe.eu "
                "(My Account Settings > Web API Security Token)."
            )

        params = {
            "securityToken": self.settings.api_token,
            "documentType": _DAY_AHEAD_DOCUMENT_TYPE,
            "in_Domain": area.value,
            "out_Domain": area.value,
            "periodStart": start.strftime("%Y%m%d%H%M"),
            "periodEnd": end.strftime("%Y%m%d%H%M"),
        }
        response = await self._http.get("", params=params)
        if response.status_code != httpx.codes.OK:
            raise EntsoeApiError(response.status_code, response.text)
        return response.text


def _parse_day_ahead_xml(area: AreaCode, xml_body: str) -> DayAheadPriceSeries:
    try:
        root = ET.fromstring(xml_body)  # noqa: S314 — trusted first-party API response
    except ET.ParseError as exc:
        raise EntsoeParseError(f"Malformed XML from ENTSO-E: {exc}") from exc

    points: list[DayAheadPrice] = []
    for timeseries in root.findall("ns:TimeSeries", _NAMESPACE):
        period = timeseries.find("ns:Period", _NAMESPACE)
        if period is None:
            continue

        start_text = period.findtext("ns:timeInterval/ns:start", namespaces=_NAMESPACE)
        if start_text is None:
            continue
        period_start = datetime.strptime(start_text, "%Y-%m-%dT%H:%MZ")

        resolution_text = period.findtext("ns:resolution", namespaces=_NAMESPACE) or "PT60M"
        resolution_minutes = _RESOLUTION_MINUTES.get(resolution_text, 60)

        for point in period.findall("ns:Point", _NAMESPACE):
            position_text = point.findtext("ns:position", namespaces=_NAMESPACE)
            price_text = point.findtext("ns:price.amount", namespaces=_NAMESPACE)
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


def _frame_from_series(series: DayAheadPriceSeries) -> pl.DataFrame:
    return pl.DataFrame([point.model_dump(mode="json") for point in series.points])


def _series_from_frame(area: AreaCode, frame: pl.DataFrame) -> DayAheadPriceSeries:
    points = [DayAheadPrice(**row) for row in frame.to_dicts()]
    return DayAheadPriceSeries(area=area, points=points)
