from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog
from entsoe_retriever import AreaCode

from backend.core.config import Settings
from backend.services.indicator_discovery import IndicatorDiscoveryService
from backend.services.outage_discovery import OutageDiscoveryService
from backend.services.price_discovery import PriceDiscoveryService

log = structlog.get_logger()


async def refresh_prices(
    settings: Settings, price_service: PriceDiscoveryService, entsoe_areas: list[AreaCode]
) -> None:
    log.info("price_refresh.start")
    try:
        await price_service.refresh(entsoe_areas, settings.default_elexon_provider)
    except Exception:
        log.exception("price_refresh.failed")
    else:
        log.info("price_refresh.done")


async def refresh_esios_indicators(
    settings: Settings, indicator_service: IndicatorDiscoveryService
) -> None:
    if not settings.esios_indicator_ids:
        return
    log.info("esios_indicator_refresh.start")
    try:
        await indicator_service.refresh_esios(settings.esios_indicator_ids)
    except Exception:
        log.exception("esios_indicator_refresh.failed")
    else:
        log.info("esios_indicator_refresh.done")


async def refresh_entsoe_generation(
    indicator_service: IndicatorDiscoveryService, entsoe_areas: list[AreaCode]
) -> None:
    log.info("entsoe_generation_refresh.start")
    try:
        await indicator_service.refresh_entsoe_generation(entsoe_areas)
    except Exception:
        log.exception("entsoe_generation_refresh.failed")
    else:
        log.info("entsoe_generation_refresh.done")


async def refresh_entsoe_wind_solar_forecast(
    indicator_service: IndicatorDiscoveryService, entsoe_areas: list[AreaCode]
) -> None:
    log.info("entsoe_wind_solar_forecast_refresh.start")
    try:
        await indicator_service.refresh_entsoe_wind_solar_forecast(entsoe_areas)
    except Exception:
        log.exception("entsoe_wind_solar_forecast_refresh.failed")
    else:
        log.info("entsoe_wind_solar_forecast_refresh.done")


async def refresh_entsoe_load(
    indicator_service: IndicatorDiscoveryService, entsoe_areas: list[AreaCode]
) -> None:
    log.info("entsoe_load_refresh.start")
    try:
        await indicator_service.refresh_entsoe_load(entsoe_areas)
    except Exception:
        log.exception("entsoe_load_refresh.failed")
    else:
        log.info("entsoe_load_refresh.done")


async def refresh_entsoe_generation_outages(
    outage_service: OutageDiscoveryService, entsoe_areas: list[AreaCode]
) -> None:
    log.info("entsoe_generation_outages_refresh.start")
    try:
        await outage_service.refresh_generation_outages(entsoe_areas)
    except Exception:
        log.exception("entsoe_generation_outages_refresh.failed")
    else:
        log.info("entsoe_generation_outages_refresh.done")


async def refresh_entsoe_transmission_outages(
    outage_service: OutageDiscoveryService, border_pairs: list[tuple[AreaCode, AreaCode]]
) -> None:
    log.info("entsoe_transmission_outages_refresh.start")
    try:
        await outage_service.refresh_transmission_outages(border_pairs)
    except Exception:
        log.exception("entsoe_transmission_outages_refresh.failed")
    else:
        log.info("entsoe_transmission_outages_refresh.done")


async def refresh_entsoe_cross_border_flows(
    indicator_service: IndicatorDiscoveryService, border_pairs: list[tuple[AreaCode, AreaCode]]
) -> None:
    log.info("entsoe_cross_border_flows_refresh.start")
    try:
        await indicator_service.refresh_entsoe_cross_border_flows(border_pairs)
    except Exception:
        log.exception("entsoe_cross_border_flows_refresh.failed")
    else:
        log.info("entsoe_cross_border_flows_refresh.done")


async def refresh_entsoe_transfer_capacity(
    indicator_service: IndicatorDiscoveryService, border_pairs: list[tuple[AreaCode, AreaCode]]
) -> None:
    log.info("entsoe_transfer_capacity_refresh.start")
    try:
        await indicator_service.refresh_entsoe_transfer_capacity(border_pairs)
    except Exception:
        log.exception("entsoe_transfer_capacity_refresh.failed")
    else:
        log.info("entsoe_transfer_capacity_refresh.done")


async def refresh_entsoe_installed_capacity(
    indicator_service: IndicatorDiscoveryService, entsoe_areas: list[AreaCode]
) -> None:
    log.info("entsoe_installed_capacity_refresh.start")
    try:
        current_year = datetime.now(timezone.utc).year
        await indicator_service.refresh_entsoe_installed_capacity(entsoe_areas, current_year)
    except Exception:
        log.exception("entsoe_installed_capacity_refresh.failed")
    else:
        log.info("entsoe_installed_capacity_refresh.done")


async def refresh_entsoe_generation_forecast_aggregated(
    indicator_service: IndicatorDiscoveryService, entsoe_areas: list[AreaCode]
) -> None:
    log.info("entsoe_generation_forecast_aggregated_refresh.start")
    try:
        await indicator_service.refresh_entsoe_generation_forecast_aggregated(entsoe_areas)
    except Exception:
        log.exception("entsoe_generation_forecast_aggregated_refresh.failed")
    else:
        log.info("entsoe_generation_forecast_aggregated_refresh.done")


async def refresh_all(
    settings: Settings,
    price_service: PriceDiscoveryService,
    indicator_service: IndicatorDiscoveryService,
    outage_service: OutageDiscoveryService,
) -> None:
    """Runs every refresh job once, concurrently — each already isolated in
    its own try/except, so one failing doesn't affect the others or raise
    here.

    Shared by two callers: the in-process APScheduler (local/dev convenience,
    ticks on its own timer) and the HTTP-triggered `/api/v1/internal/refresh`
    route (production, where the process runs on a host that suspends when
    idle — an external scheduler like a GitHub Actions cron calls that route
    instead of relying on an always-on process to tick internally).
    """
    entsoe_areas = [AreaCode(area) for area in settings.entsoe_areas]
    border_pairs = [
        (AreaCode(area_in), AreaCode(area_out)) for area_in, area_out in settings.entsoe_border_pairs
    ]

    await asyncio.gather(
        refresh_prices(settings, price_service, entsoe_areas),
        refresh_esios_indicators(settings, indicator_service),
        refresh_entsoe_generation(indicator_service, entsoe_areas),
        refresh_entsoe_wind_solar_forecast(indicator_service, entsoe_areas),
        refresh_entsoe_load(indicator_service, entsoe_areas),
        refresh_entsoe_generation_outages(outage_service, entsoe_areas),
        refresh_entsoe_transmission_outages(outage_service, border_pairs),
        refresh_entsoe_cross_border_flows(indicator_service, border_pairs),
        refresh_entsoe_transfer_capacity(indicator_service, border_pairs),
        refresh_entsoe_installed_capacity(indicator_service, entsoe_areas),
        refresh_entsoe_generation_forecast_aggregated(indicator_service, entsoe_areas),
    )
