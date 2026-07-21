from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from elexon_retriever import ElexonClient
from entsoe_retriever import AreaCode, EntsoeClient
from esios_retriever import EsiosClient
from esios_retriever.client import DAY_AHEAD_PRICE_INDICATOR_ID

from backend.services.storage import PriceRepository

log = structlog.get_logger()


class PriceDiscoveryService:
    """Aggregates day-ahead price data across all connected sources into one
    normalized shape and persists it to Postgres via PriceRepository.

    Each source is fetched independently and a failure in one (expired
    token, upstream outage, ...) doesn't block the others — whatever
    succeeded still gets upserted, and the failure is just logged.

    This is the seam for adding a new price source: fetch it here, normalize
    its rows to the `prices` table shape (source, area, timestamp,
    price_per_mwh, currency), append them to `rows` inside its own try/except.
    """

    def __init__(
        self,
        entsoe_client: EntsoeClient,
        elexon_client: ElexonClient,
        esios_client: EsiosClient,
        repository: PriceRepository,
    ) -> None:
        self._entsoe = entsoe_client
        self._elexon = elexon_client
        self._esios = esios_client
        self._repository = repository

    async def refresh(self, areas: list[AreaCode], elexon_provider: str) -> None:
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(days=1)
        rows: list[dict] = []

        # Each area isolated too, not just each source — one country's fetch
        # failing (rate limit, transient outage) shouldn't block the others.
        for area in areas:
            try:
                entsoe_series = await self._entsoe.get_day_ahead_prices(area, window_start, now)
                rows.extend(
                    {
                        "source": "entsoe",
                        "area": point.area.value,
                        "timestamp": point.timestamp,
                        "price_per_mwh": point.price_eur_mwh,
                        "currency": "EUR",
                    }
                    for point in entsoe_series.points
                )
            except Exception:
                log.exception("entsoe.refresh.failed", area=area.name)

        try:
            elexon_series = await self._elexon.get_market_index_prices(
                window_start.date(), now.date(), elexon_provider
            )
            rows.extend(
                {
                    "source": "elexon",
                    "area": "GB",
                    "timestamp": point.start_time,
                    "price_per_mwh": point.price_gbp_mwh,
                    "currency": "GBP",
                }
                for point in elexon_series.points
            )
        except Exception:
            log.exception("elexon.refresh.failed")

        try:
            esios_series = await self._esios.get_indicator(
                DAY_AHEAD_PRICE_INDICATOR_ID, window_start, now
            )
            rows.extend(
                {
                    "source": "esios",
                    "area": "ES",
                    "timestamp": point.timestamp,
                    "price_per_mwh": point.value,
                    "currency": "EUR",
                }
                for point in esios_series.values
            )
        except Exception:
            log.exception("esios.refresh.failed")

        if rows:
            await self._repository.upsert_prices(rows)

    async def latest(self, source: str | None = None, area: str | None = None) -> list[dict]:
        return await self._repository.query(source=source, area=area)
