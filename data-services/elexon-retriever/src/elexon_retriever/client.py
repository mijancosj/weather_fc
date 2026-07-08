from __future__ import annotations

from datetime import date

import httpx
import polars as pl
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from elexon_retriever.cache import ParquetCache
from elexon_retriever.config import ElexonSettings, get_settings
from elexon_retriever.exceptions import ElexonApiError
from elexon_retriever.models import MarketIndexPrice, MarketIndexPriceSeries


class ElexonClient:
    """Async client for the Elexon Insights Solution (BMRS) REST API.

    Docs: https://bmrs.elexon.co.uk/api-documentation
    """

    def __init__(self, settings: ElexonSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self._cache = ParquetCache(self.settings.cache_dir, self.settings.cache_ttl_seconds)
        self._http = httpx.AsyncClient(
            base_url=self.settings.base_url,
            timeout=self.settings.request_timeout_seconds,
        )

    async def __aenter__(self) -> ElexonClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get_market_index_prices(
        self,
        start: date,
        end: date,
        data_provider: str = "APX",
        use_cache: bool = True,
    ) -> MarketIndexPriceSeries:
        """Fetch GB market index (day-ahead reference) prices over [start, end]."""
        cache_key = f"market_index_{data_provider}_{start:%Y%m%d}_{end:%Y%m%d}"

        if use_cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return _series_from_frame(cached)

        payload = await self._fetch(start, end, data_provider)
        series = _parse_market_index_payload(payload)

        if use_cache and series.points:
            self._cache.set(cache_key, _frame_from_series(series))

        return series

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    async def _fetch(self, start: date, end: date, data_provider: str) -> list[dict]:
        response = await self._http.get(
            "/balancing/pricing/market-index",
            params={
                "from": start.isoformat(),
                "to": end.isoformat(),
                "dataProviders": data_provider,
            },
            headers=self._auth_headers(),
        )
        if response.status_code != httpx.codes.OK:
            raise ElexonApiError(response.status_code, response.text)
        return response.json()

    def _auth_headers(self) -> dict[str, str]:
        if self.settings.api_key:
            return {"Authorization": f"Bearer {self.settings.api_key}"}
        return {}


def _parse_market_index_payload(payload: list[dict]) -> MarketIndexPriceSeries:
    points = [
        MarketIndexPrice(
            settlement_date=item["settlementDate"],
            settlement_period=item["settlementPeriod"],
            price_gbp_mwh=item["price"],
            volume_mwh=item.get("volume"),
            data_provider=item["dataProvider"],
        )
        for item in payload
    ]
    return MarketIndexPriceSeries(points=points)


def _frame_from_series(series: MarketIndexPriceSeries) -> pl.DataFrame:
    return pl.DataFrame([point.model_dump(mode="json") for point in series.points])


def _series_from_frame(frame: pl.DataFrame) -> MarketIndexPriceSeries:
    points = [MarketIndexPrice(**row) for row in frame.to_dicts()]
    return MarketIndexPriceSeries(points=points)
