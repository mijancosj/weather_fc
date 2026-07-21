from __future__ import annotations

from datetime import datetime, timezone

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from entsoe_retriever import AreaCode

from backend.core.config import Settings
from backend.services.indicator_discovery import IndicatorDiscoveryService
from backend.services.outage_discovery import OutageDiscoveryService
from backend.services.price_discovery import PriceDiscoveryService

log = structlog.get_logger()


def start_scheduler(
    settings: Settings,
    price_service: PriceDiscoveryService,
    indicator_service: IndicatorDiscoveryService,
    outage_service: OutageDiscoveryService,
) -> AsyncIOScheduler:
    """Periodically refreshes prices and configured indicators from all retrievers.

    Failures are logged, not raised — a bad fetch shouldn't take the API down;
    it should just leave the last-known-good data in place until the next tick.
    """
    scheduler = AsyncIOScheduler()

    entsoe_areas = [AreaCode(area) for area in settings.entsoe_areas]
    border_pairs = [
        (AreaCode(area_in), AreaCode(area_out)) for area_in, area_out in settings.entsoe_border_pairs
    ]

    async def _price_job() -> None:
        log.info("price_refresh.start")
        try:
            await price_service.refresh(entsoe_areas, settings.default_elexon_provider)
        except Exception:
            log.exception("price_refresh.failed")
        else:
            log.info("price_refresh.done")

    async def _esios_indicator_job() -> None:
        if not settings.esios_indicator_ids:
            return
        log.info("esios_indicator_refresh.start")
        try:
            await indicator_service.refresh_esios(settings.esios_indicator_ids)
        except Exception:
            log.exception("esios_indicator_refresh.failed")
        else:
            log.info("esios_indicator_refresh.done")

    async def _entsoe_generation_job() -> None:
        log.info("entsoe_generation_refresh.start")
        try:
            await indicator_service.refresh_entsoe_generation(entsoe_areas)
        except Exception:
            log.exception("entsoe_generation_refresh.failed")
        else:
            log.info("entsoe_generation_refresh.done")

    async def _entsoe_wind_solar_forecast_job() -> None:
        log.info("entsoe_wind_solar_forecast_refresh.start")
        try:
            await indicator_service.refresh_entsoe_wind_solar_forecast(entsoe_areas)
        except Exception:
            log.exception("entsoe_wind_solar_forecast_refresh.failed")
        else:
            log.info("entsoe_wind_solar_forecast_refresh.done")

    async def _entsoe_load_job() -> None:
        log.info("entsoe_load_refresh.start")
        try:
            await indicator_service.refresh_entsoe_load(entsoe_areas)
        except Exception:
            log.exception("entsoe_load_refresh.failed")
        else:
            log.info("entsoe_load_refresh.done")

    async def _entsoe_generation_outages_job() -> None:
        log.info("entsoe_generation_outages_refresh.start")
        try:
            await outage_service.refresh_generation_outages(entsoe_areas)
        except Exception:
            log.exception("entsoe_generation_outages_refresh.failed")
        else:
            log.info("entsoe_generation_outages_refresh.done")

    async def _entsoe_transmission_outages_job() -> None:
        log.info("entsoe_transmission_outages_refresh.start")
        try:
            await outage_service.refresh_transmission_outages(border_pairs)
        except Exception:
            log.exception("entsoe_transmission_outages_refresh.failed")
        else:
            log.info("entsoe_transmission_outages_refresh.done")

    async def _entsoe_cross_border_flows_job() -> None:
        log.info("entsoe_cross_border_flows_refresh.start")
        try:
            await indicator_service.refresh_entsoe_cross_border_flows(border_pairs)
        except Exception:
            log.exception("entsoe_cross_border_flows_refresh.failed")
        else:
            log.info("entsoe_cross_border_flows_refresh.done")

    async def _entsoe_transfer_capacity_job() -> None:
        log.info("entsoe_transfer_capacity_refresh.start")
        try:
            await indicator_service.refresh_entsoe_transfer_capacity(border_pairs)
        except Exception:
            log.exception("entsoe_transfer_capacity_refresh.failed")
        else:
            log.info("entsoe_transfer_capacity_refresh.done")

    async def _entsoe_installed_capacity_job() -> None:
        log.info("entsoe_installed_capacity_refresh.start")
        try:
            current_year = datetime.now(timezone.utc).year
            await indicator_service.refresh_entsoe_installed_capacity(entsoe_areas, current_year)
        except Exception:
            log.exception("entsoe_installed_capacity_refresh.failed")
        else:
            log.info("entsoe_installed_capacity_refresh.done")

    async def _entsoe_generation_forecast_aggregated_job() -> None:
        log.info("entsoe_generation_forecast_aggregated_refresh.start")
        try:
            await indicator_service.refresh_entsoe_generation_forecast_aggregated(entsoe_areas)
        except Exception:
            log.exception("entsoe_generation_forecast_aggregated_refresh.failed")
        else:
            log.info("entsoe_generation_forecast_aggregated_refresh.done")

    scheduler.add_job(_price_job, "interval", minutes=settings.refresh_interval_minutes)
    scheduler.add_job(_esios_indicator_job, "interval", minutes=settings.refresh_interval_minutes)
    scheduler.add_job(_entsoe_generation_job, "interval", minutes=settings.refresh_interval_minutes)
    scheduler.add_job(
        _entsoe_wind_solar_forecast_job, "interval", minutes=settings.refresh_interval_minutes
    )
    scheduler.add_job(_entsoe_load_job, "interval", minutes=settings.refresh_interval_minutes)
    scheduler.add_job(
        _entsoe_generation_outages_job, "interval", minutes=settings.refresh_interval_minutes
    )
    scheduler.add_job(
        _entsoe_transmission_outages_job, "interval", minutes=settings.refresh_interval_minutes
    )
    scheduler.add_job(
        _entsoe_cross_border_flows_job, "interval", minutes=settings.refresh_interval_minutes
    )
    scheduler.add_job(
        _entsoe_transfer_capacity_job, "interval", minutes=settings.refresh_interval_minutes
    )
    scheduler.add_job(
        _entsoe_installed_capacity_job, "interval", minutes=settings.refresh_interval_minutes
    )
    scheduler.add_job(
        _entsoe_generation_forecast_aggregated_job,
        "interval",
        minutes=settings.refresh_interval_minutes,
    )
    scheduler.start()
    return scheduler
