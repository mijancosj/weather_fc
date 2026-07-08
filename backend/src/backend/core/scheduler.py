from __future__ import annotations

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from entsoe_retriever import AreaCode

from backend.core.config import Settings
from backend.services.price_discovery import PriceDiscoveryService

log = structlog.get_logger()


def start_scheduler(settings: Settings, service: PriceDiscoveryService) -> AsyncIOScheduler:
    """Periodically refreshes the local price warehouse from both retrievers.

    Failures are logged, not raised — a bad fetch shouldn't take the API down;
    it should just leave the last-known-good data in place until the next tick.
    """
    scheduler = AsyncIOScheduler()

    async def _job() -> None:
        log.info("refresh.start")
        try:
            await service.refresh(
                AreaCode(settings.default_entsoe_area), settings.default_elexon_provider
            )
        except Exception:
            log.exception("refresh.failed")
        else:
            log.info("refresh.done")

    scheduler.add_job(_job, "interval", minutes=settings.refresh_interval_minutes)
    scheduler.start()
    return scheduler
