from fastapi import APIRouter, Depends, Query

from backend.api.deps import get_price_discovery_service
from backend.services.price_discovery import PriceDiscoveryService

router = APIRouter(prefix="/api/v1/prices", tags=["prices"])


@router.get("/day-ahead")
async def day_ahead_prices(
    source: str | None = Query(default=None, description="Filter by source: entsoe | elexon"),
    area: str | None = Query(default=None, description="Filter by bidding zone / market area"),
    service: PriceDiscoveryService = Depends(get_price_discovery_service),
) -> list[dict]:
    return await service.latest(source=source, area=area)
