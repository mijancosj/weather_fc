from __future__ import annotations

from datetime import datetime, timedelta, timezone

from elexon_retriever import ElexonClient
from entsoe_retriever import AreaCode, EntsoeClient

from backend.services.storage import PriceRepository


class PriceDiscoveryService:
    """Aggregates day-ahead price data across all connected sources into one
    normalized shape and persists it to Postgres via PriceRepository.

    This is the seam for adding a new data source: fetch it here, normalize
    its rows to the `prices` table shape (source, area, timestamp,
    price_per_mwh, currency), and append them to `rows` in `refresh()`.
    """

    def __init__(
        self,
        entsoe_client: EntsoeClient,
        elexon_client: ElexonClient,
        repository: PriceRepository,
    ) -> None:
        self._entsoe = entsoe_client
        self._elexon = elexon_client
        self._repository = repository

    async def refresh(self, area: AreaCode, elexon_provider: str) -> None:
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(days=1)

        entsoe_series = await self._entsoe.get_day_ahead_prices(area, window_start, now)
        elexon_series = await self._elexon.get_market_index_prices(
            window_start.date(), now.date(), elexon_provider
        )

        rows = [
            {
                "source": "entsoe",
                "area": point.area.value,
                "timestamp": point.timestamp,
                "price_per_mwh": point.price_eur_mwh,
                "currency": "EUR",
            }
            for point in entsoe_series.points
        ] + [
            {
                "source": "elexon",
                "area": "GB",
                "timestamp": datetime.combine(point.settlement_date, datetime.min.time()),
                "price_per_mwh": point.price_gbp_mwh,
                "currency": "GBP",
            }
            for point in elexon_series.points
        ]

        await self._repository.upsert_prices(rows)

    async def latest(self, source: str | None = None, area: str | None = None) -> list[dict]:
        return await self._repository.query(source=source, area=area)
