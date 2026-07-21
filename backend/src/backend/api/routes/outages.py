from fastapi import APIRouter, Depends, Query

from backend.api.deps import get_outage_discovery_service
from backend.services.outage_discovery import OutageDiscoveryService

router = APIRouter(prefix="/api/v1/outages", tags=["outages"])


@router.get("")
async def outages(
    resource_type: str | None = Query(
        default=None, description="Filter by 'generation' or 'transmission'"
    ),
    area: str | None = Query(
        default=None, description="Filter by EIC area code (matches area, in_area, or out_area)"
    ),
    active_only: bool = Query(
        default=False, description="Only outages whose declared period covers right now"
    ),
    service: OutageDiscoveryService = Depends(get_outage_discovery_service),
) -> list[dict]:
    """Stored, scheduler-refreshed ENTSO-E outage notifications (planned
    maintenance + forced unavailability) for generation units and
    interconnector transmission capacity. Latest revision per event only.
    """
    return await service.latest(resource_type=resource_type, area=area, active_only=active_only)
