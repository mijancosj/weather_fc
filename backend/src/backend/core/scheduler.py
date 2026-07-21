from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from backend.core.config import Settings
from backend.core.refresh_jobs import refresh_all
from backend.services.indicator_discovery import IndicatorDiscoveryService
from backend.services.outage_discovery import OutageDiscoveryService
from backend.services.price_discovery import PriceDiscoveryService


def start_scheduler(
    settings: Settings,
    price_service: PriceDiscoveryService,
    indicator_service: IndicatorDiscoveryService,
    outage_service: OutageDiscoveryService,
) -> AsyncIOScheduler:
    """Ticks `refresh_all` on an interval — local/dev convenience so
    `scripts/dev.ps1` "just works" with no external scheduler needed.

    In production on a host that suspends the process when idle (most free
    tiers), this alone isn't reliable — pair it with the
    `/api/v1/internal/refresh` route triggered by an external cron (see
    docs/deployment.md) so refreshes still happen while the process is
    asleep between requests. Harmless to leave running either way: both
    paths call the same idempotent `refresh_all`.
    """
    scheduler = AsyncIOScheduler()

    async def _tick() -> None:
        await refresh_all(settings, price_service, indicator_service, outage_service)

    scheduler.add_job(_tick, "interval", minutes=settings.refresh_interval_minutes)
    scheduler.start()
    return scheduler
