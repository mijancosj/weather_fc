from fastapi import APIRouter, Depends, Header, HTTPException

from backend.api.deps import (
    get_indicator_discovery_service,
    get_outage_discovery_service,
    get_price_discovery_service,
)
from backend.core.config import Settings, get_settings
from backend.core.refresh_jobs import refresh_all
from backend.services.indicator_discovery import IndicatorDiscoveryService
from backend.services.outage_discovery import OutageDiscoveryService
from backend.services.price_discovery import PriceDiscoveryService

router = APIRouter(prefix="/api/v1/internal", tags=["internal"])


@router.post("/refresh")
async def trigger_refresh(
    x_refresh_token: str = Header(default=""),
    settings: Settings = Depends(get_settings),
    price_service: PriceDiscoveryService = Depends(get_price_discovery_service),
    indicator_service: IndicatorDiscoveryService = Depends(get_indicator_discovery_service),
    outage_service: OutageDiscoveryService = Depends(get_outage_discovery_service),
) -> dict:
    """Runs one full refresh cycle on demand — the same work the in-process
    scheduler does on its own timer (see core/refresh_jobs.py).

    Meant for a host that suspends the process when idle (most free tiers):
    an external scheduler (e.g. a GitHub Actions cron) calls this instead of
    relying on an always-on process to tick internally. Requires
    BACKEND_REFRESH_TOKEN to be set — the route is disabled (503) if it
    isn't, so this can't be triggered by accident on an unconfigured
    deployment.
    """
    if not settings.refresh_token:
        raise HTTPException(status_code=503, detail="BACKEND_REFRESH_TOKEN is not configured")
    if x_refresh_token != settings.refresh_token:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Refresh-Token header")

    await refresh_all(settings, price_service, indicator_service, outage_service)
    return {"status": "ok"}
