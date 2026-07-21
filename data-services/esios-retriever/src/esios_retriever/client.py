from __future__ import annotations

from datetime import datetime

import httpx
import polars as pl
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from esios_retriever.cache import ParquetCache
from esios_retriever.config import EsiosSettings, get_settings
from esios_retriever.exceptions import EsiosApiError, EsiosConfigurationError, EsiosParseError
from esios_retriever.models import IndicatorSeries, IndicatorSummary, IndicatorValue

_ACCEPT_HEADER = "application/json; application/vnd.esios-api-v1+json"

DAY_AHEAD_PRICE_INDICATOR_ID = 600
"""'Precio mercado SPOT Diario' — Spain's day-ahead market price."""


class EsiosClient:
    """Async client for the ESIOS (Red Eléctrica de España) public REST API.

    Docs: https://api.esios.ree.es/ — covers day-ahead prices, demand,
    generation by technology, and many other Spanish power market indicators,
    each identified by a numeric indicator ID. Use `list_indicators` to
    discover IDs for whatever fundamental data you need.
    """

    def __init__(self, settings: EsiosSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self._cache = ParquetCache(self.settings.cache_dir, self.settings.cache_ttl_seconds)
        self._http = httpx.AsyncClient(
            base_url=self.settings.base_url,
            timeout=self.settings.request_timeout_seconds,
        )

    async def __aenter__(self) -> EsiosClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def list_indicators(self, locale: str = "es") -> list[IndicatorSummary]:
        """List all indicators available on the platform (id + name) — the
        starting point for finding the indicator_id of whatever series you need.
        """
        payload = await self._get("/indicators", params={"locale": locale})
        try:
            return [
                IndicatorSummary(id=item["id"], name=item["name"])
                for item in payload["indicators"]
            ]
        except (KeyError, TypeError) as exc:
            raise EsiosParseError(f"Unexpected response shape from ESIOS: {exc}") from exc

    async def get_indicator(
        self,
        indicator_id: int,
        start: datetime,
        end: datetime,
        geo_ids: list[int] | None = None,
        time_trunc: str = "hour",
        use_cache: bool = True,
    ) -> IndicatorSeries:
        """Fetch one indicator's time series over [start, end]."""
        cache_key = f"indicator_{indicator_id}_{time_trunc}_{start:%Y%m%d%H}_{end:%Y%m%d%H}"

        if use_cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return _series_from_frame(indicator_id, cached)

        params: dict[str, object] = {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "time_trunc": time_trunc,
        }
        if geo_ids:
            params["geo_ids[]"] = geo_ids

        payload = await self._get(f"/indicators/{indicator_id}", params=params)
        series = _parse_indicator_payload(indicator_id, payload)

        if use_cache and series.values:
            self._cache.set(cache_key, _frame_from_series(series))

        return series

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    async def _get(self, path: str, params: dict) -> dict:
        if not self.settings.api_token:
            raise EsiosConfigurationError(
                "ESIOS_API_TOKEN is not set. Request one by emailing consultasios@ree.es "
                "with subject 'Personal token request'."
            )

        response = await self._http.get(
            path,
            params=params,
            headers={
                "Accept": _ACCEPT_HEADER,
                "Content-Type": "application/json",
                "x-api-key": self.settings.api_token,
            },
        )
        if response.status_code != httpx.codes.OK:
            raise EsiosApiError(response.status_code, response.text)
        return response.json()


def _parse_indicator_payload(indicator_id: int, payload: dict) -> IndicatorSeries:
    try:
        indicator = payload["indicator"]
        name = indicator.get("name", "")
        values = [
            IndicatorValue(
                timestamp=datetime.fromisoformat(item["tz_time"]),
                value=float(item["value"]),
                geo_id=item.get("geo_id"),
                geo_name=item.get("geo_name"),
            )
            for item in indicator["values"]
        ]
    except (KeyError, ValueError, TypeError) as exc:
        raise EsiosParseError(f"Unexpected response shape from ESIOS: {exc}") from exc

    return IndicatorSeries(indicator_id=indicator_id, name=name, values=values)


def _frame_from_series(series: IndicatorSeries) -> pl.DataFrame:
    return pl.DataFrame(
        [{**v.model_dump(mode="json"), "indicator_name": series.name} for v in series.values]
    )


def _series_from_frame(indicator_id: int, frame: pl.DataFrame) -> IndicatorSeries:
    rows = frame.to_dicts()
    name = rows[0].pop("indicator_name", "") if rows else ""
    for row in rows:
        row.pop("indicator_name", None)
    values = [IndicatorValue(**row) for row in rows]
    return IndicatorSeries(indicator_id=indicator_id, name=name, values=values)
