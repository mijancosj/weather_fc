from datetime import datetime, timedelta, timezone

from esios_retriever import EsiosClient
from esios_retriever.exceptions import EsiosApiError, EsiosConfigurationError, EsiosParseError
from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.deps import get_esios_client, get_indicator_discovery_service
from backend.services.indicator_discovery import IndicatorDiscoveryService

router = APIRouter(prefix="/api/v1/indicators", tags=["indicators"])


async def _call_esios(coro):
    """Translate esios-retriever's exceptions into HTTP responses instead of
    letting them surface as opaque 500s — these live endpoints call ESIOS
    synchronously on the request path, unlike the scheduler which just logs
    and skips a failed refresh.
    """
    try:
        return await coro
    except EsiosConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (EsiosApiError, EsiosParseError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/catalog")
async def list_available_indicators(
    locale: str = Query(default="es"),
    esios_client: EsiosClient = Depends(get_esios_client),
) -> list[dict]:
    """Live discovery of every indicator ESIOS publishes — use this to find
    the indicator_id for whatever fundamental data you need, then add it to
    BACKEND_ESIOS_INDICATOR_IDS to have it tracked automatically.
    """
    indicators = await _call_esios(esios_client.list_indicators(locale=locale))
    return [indicator.model_dump() for indicator in indicators]


@router.get("/{indicator_id}/preview")
async def preview_indicator(
    indicator_id: int,
    days: int = Query(default=1, ge=1, le=31),
    esios_client: EsiosClient = Depends(get_esios_client),
) -> dict:
    """One-off live fetch of a single indicator's recent values — doesn't
    touch Postgres. Useful for checking what an indicator looks like before
    deciding to add it to BACKEND_ESIOS_INDICATOR_IDS for scheduled tracking.
    """
    now = datetime.now(timezone.utc)
    series = await _call_esios(
        esios_client.get_indicator(indicator_id, now - timedelta(days=days), now)
    )
    return series.model_dump()


@router.get("/observations")
async def observations(
    source: str | None = Query(default=None, description="Filter by source, e.g. esios"),
    indicator_id: str | None = Query(default=None, description="Filter by indicator ID"),
    geo_name: str | None = Query(
        default=None, description="Filter by area/country, e.g. FR, ES, PT, GB"
    ),
    service: IndicatorDiscoveryService = Depends(get_indicator_discovery_service),
) -> list[dict]:
    """Stored, scheduler-refreshed indicator observations from Postgres."""
    return await service.latest(source=source, indicator_id=indicator_id, geo_name=geo_name)
