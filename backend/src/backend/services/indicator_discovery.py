from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from entsoe_retriever import PSR_TYPE_NAMES, AreaCode, EntsoeClient
from esios_retriever import EsiosClient

from backend.services.storage import IndicatorRepository

log = structlog.get_logger()


class IndicatorDiscoveryService:
    """Refreshes generic fundamental data (demand, generation by technology,
    or anything else that isn't a price) into Postgres — from ESIOS
    indicators and ENTSO-E's actual-generation-by-type feed.

    Which ESIOS indicators to track is configuration
    (`BACKEND_ESIOS_INDICATOR_IDS`), not code — use
    `EsiosClient.list_indicators()` to find IDs for whatever fundamental data
    your analysis needs, then add them there. ENTSO-E's generation-by-type
    feed always returns every production type ENTSO-E has for the area
    (wind, solar, hydro, nuclear, ...), so there's nothing to configure there.
    """

    def __init__(
        self,
        esios_client: EsiosClient,
        entsoe_client: EntsoeClient,
        repository: IndicatorRepository,
    ) -> None:
        self._esios = esios_client
        self._entsoe = entsoe_client
        self._repository = repository

    async def refresh_esios(self, indicator_ids: list[int]) -> None:
        if not indicator_ids:
            return

        now = datetime.now(timezone.utc)
        window_start = now - timedelta(days=1)
        rows: list[dict] = []

        for indicator_id in indicator_ids:
            try:
                series = await self._esios.get_indicator(indicator_id, window_start, now)
            except Exception:
                log.exception("esios.indicator.refresh.failed", indicator_id=indicator_id)
                continue

            rows.extend(
                {
                    "source": "esios",
                    "indicator_id": str(indicator_id),
                    "indicator_name": series.name or None,
                    "geo_id": point.geo_id or 0,
                    "geo_name": point.geo_name,
                    "timestamp": point.timestamp,
                    "value": point.value,
                    "unit": None,
                }
                for point in series.values
            )

        if rows:
            await self._repository.upsert_observations(rows)

    async def refresh_entsoe_generation(self, areas: list[AreaCode]) -> None:
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(days=1)
        rows: list[dict] = []

        for area in areas:
            try:
                series = await self._entsoe.get_generation_by_type(area, window_start, now)
            except Exception:
                log.exception("entsoe.generation.refresh.failed", area=area.name)
                continue

            # indicator_id encodes the area too (not just geo_id) since geo_id
            # is a plain int sized for ESIOS's numeric geo scheme — ENTSO-E
            # areas are EIC strings, so folding the area into the key here is
            # what keeps (source, indicator_id, geo_id, timestamp) unique per
            # area+technology now that this covers multiple areas. Storage
            # technologies report generation and consumption as separate
            # series for the same timestamp (see GenerationValue.is_consumption)
            # — the ":consumption" suffix keeps those from colliding too.
            rows.extend(
                {
                    "source": "entsoe",
                    "indicator_id": (
                        f"generation:{point.psr_type}:{area.value}"
                        + (":consumption" if point.is_consumption else "")
                    ),
                    "indicator_name": (
                        f"Generation — {PSR_TYPE_NAMES.get(point.psr_type, point.psr_type)}"
                        + (" (consumption)" if point.is_consumption else "")
                    ),
                    "geo_id": 0,
                    "geo_name": area.name,
                    "timestamp": point.timestamp,
                    "value": point.quantity_mw,
                    "unit": "MW",
                }
                for point in series.points
            )

        if rows:
            await self._repository.upsert_observations(rows)

    async def refresh_entsoe_wind_solar_forecast(self, areas: list[AreaCode]) -> None:
        """Day-ahead wind/solar generation forecast. Diffing this against
        `refresh_entsoe_generation`'s actuals for the same window is the
        classic forecast-error trading signal — under-forecast wind/solar
        tends to push intraday prices down, over-forecast pushes them up.
        """
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(days=1)
        window_end = now + timedelta(days=1)  # forecasts extend into the future
        rows: list[dict] = []

        for area in areas:
            try:
                series = await self._entsoe.get_wind_solar_forecast(area, window_start, window_end)
            except Exception:
                log.exception("entsoe.wind_solar_forecast.refresh.failed", area=area.name)
                continue

            rows.extend(
                {
                    "source": "entsoe",
                    "indicator_id": f"generation_forecast:{point.psr_type}:{area.value}",
                    "indicator_name": (
                        f"Generation forecast — {PSR_TYPE_NAMES.get(point.psr_type, point.psr_type)}"
                    ),
                    "geo_id": 0,
                    "geo_name": area.name,
                    "timestamp": point.timestamp,
                    "value": point.quantity_mw,
                    "unit": "MW",
                }
                for point in series.points
            )

        if rows:
            await self._repository.upsert_observations(rows)

    async def refresh_entsoe_load(self, areas: list[AreaCode]) -> None:
        """Total system load (demand): day-ahead forecast + realised/actual.
        Diffing forecast vs. actual is the classic demand-surprise trading
        signal — same idea as the wind/solar forecast diff, for demand
        instead of supply.
        """
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(days=1)
        window_end = now + timedelta(days=1)  # forecast extends into the future
        rows: list[dict] = []

        for area in areas:
            try:
                forecast = await self._entsoe.get_load_forecast(area, now, window_end)
                rows.extend(
                    {
                        "source": "entsoe",
                        "indicator_id": f"load:forecast:{area.value}",
                        "indicator_name": "Total system load — day-ahead forecast",
                        "geo_id": 0,
                        "geo_name": area.name,
                        "timestamp": point.timestamp,
                        "value": point.load_mw,
                        "unit": "MW",
                    }
                    for point in forecast.points
                )
            except Exception:
                log.exception("entsoe.load_forecast.refresh.failed", area=area.name)

            try:
                actual = await self._entsoe.get_load_actual(area, window_start, now)
                rows.extend(
                    {
                        "source": "entsoe",
                        "indicator_id": f"load:actual:{area.value}",
                        "indicator_name": "Total system load — actual",
                        "geo_id": 0,
                        "geo_name": area.name,
                        "timestamp": point.timestamp,
                        "value": point.load_mw,
                        "unit": "MW",
                    }
                    for point in actual.points
                )
            except Exception:
                log.exception("entsoe.load_actual.refresh.failed", area=area.name)

        if rows:
            await self._repository.upsert_observations(rows)

    async def refresh_entsoe_cross_border_flows(
        self, border_pairs: list[tuple[AreaCode, AreaCode]]
    ) -> None:
        """Actual physical energy flow across each configured interconnector
        border — confirmed live to be direction-specific (in_Domain/out_Domain),
        so each configured pair is fetched exactly as configured, not both ways.
        """
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(days=1)
        rows: list[dict] = []

        for area_in, area_out in border_pairs:
            try:
                series = await self._entsoe.get_cross_border_flows(area_in, area_out, window_start, now)
            except Exception:
                log.exception(
                    "entsoe.cross_border_flows.refresh.failed",
                    area_in=area_in.name,
                    area_out=area_out.name,
                )
                continue

            rows.extend(
                {
                    "source": "entsoe",
                    "indicator_id": f"flow:{area_in.value}:{area_out.value}",
                    "indicator_name": f"Cross-border flow — {area_in.name} to {area_out.name}",
                    "geo_id": 0,
                    "geo_name": f"{area_in.name}-{area_out.name}",
                    "timestamp": point.timestamp,
                    "value": point.flow_mw,
                    "unit": "MW",
                }
                for point in series.points
            )

        if rows:
            await self._repository.upsert_observations(rows)

    async def refresh_entsoe_transfer_capacity(
        self, border_pairs: list[tuple[AreaCode, AreaCode]]
    ) -> None:
        """Day-ahead available transfer capacity (ATC) — the commercial
        limit, not the physical flow (see `refresh_entsoe_cross_border_flows`).
        Diffing flow against ATC shows how much headroom is left on a border,
        a classic congestion/spread-risk signal.
        """
        now = datetime.now(timezone.utc)
        window_end = now + timedelta(days=2)
        rows: list[dict] = []

        for area_in, area_out in border_pairs:
            try:
                series = await self._entsoe.get_transfer_capacity(area_in, area_out, now, window_end)
            except Exception:
                log.exception(
                    "entsoe.transfer_capacity.refresh.failed",
                    area_in=area_in.name,
                    area_out=area_out.name,
                )
                continue

            rows.extend(
                {
                    "source": "entsoe",
                    "indicator_id": f"atc:{area_in.value}:{area_out.value}",
                    "indicator_name": f"Available transfer capacity — {area_in.name} to {area_out.name}",
                    "geo_id": 0,
                    "geo_name": f"{area_in.name}-{area_out.name}",
                    "timestamp": point.timestamp,
                    "value": point.capacity_mw,
                    "unit": "MW",
                }
                for point in series.points
            )

        if rows:
            await self._repository.upsert_observations(rows)

    async def refresh_entsoe_installed_capacity(self, areas: list[AreaCode], year: int) -> None:
        """Installed generation capacity per technology for the given year —
        structural context (paired with actual generation to see headroom),
        not something that needs refreshing more than a few times a year, but
        cheap enough to just include on every scheduler tick.
        """
        rows: list[dict] = []

        for area in areas:
            try:
                series = await self._entsoe.get_installed_capacity(area, year)
            except Exception:
                log.exception("entsoe.installed_capacity.refresh.failed", area=area.name)
                continue

            rows.extend(
                {
                    "source": "entsoe",
                    "indicator_id": f"installed_capacity:{point.psr_type}:{area.value}",
                    "indicator_name": (
                        f"Installed capacity — {PSR_TYPE_NAMES.get(point.psr_type, point.psr_type)}"
                    ),
                    "geo_id": 0,
                    "geo_name": area.name,
                    "timestamp": point.year_start,
                    "value": point.capacity_mw,
                    "unit": "MW",
                }
                for point in series.points
            )

        if rows:
            await self._repository.upsert_observations(rows)

    async def refresh_entsoe_generation_forecast_aggregated(self, areas: list[AreaCode]) -> None:
        """Total day-ahead generation forecast across every technology
        combined — pairs with `refresh_entsoe_load`'s forecast as a single
        supply-vs-demand trading signal, distinct from the per-technology
        wind/solar forecast in `refresh_entsoe_wind_solar_forecast`.
        """
        now = datetime.now(timezone.utc)
        window_end = now + timedelta(days=1)
        rows: list[dict] = []

        for area in areas:
            try:
                series = await self._entsoe.get_generation_forecast_aggregated(area, now, window_end)
            except Exception:
                log.exception("entsoe.generation_forecast_aggregated.refresh.failed", area=area.name)
                continue

            rows.extend(
                {
                    "source": "entsoe",
                    "indicator_id": f"generation_forecast_aggregated:{area.value}",
                    "indicator_name": "Generation forecast — all technologies combined",
                    "geo_id": 0,
                    "geo_name": area.name,
                    "timestamp": point.timestamp,
                    "value": point.forecast_mw,
                    "unit": "MW",
                }
                for point in series.points
            )

        if rows:
            await self._repository.upsert_observations(rows)

    async def latest(
        self,
        source: str | None = None,
        indicator_id: str | None = None,
        geo_name: str | None = None,
    ) -> list[dict]:
        return await self._repository.query(source=source, indicator_id=indicator_id, geo_name=geo_name)
