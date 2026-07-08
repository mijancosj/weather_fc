from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/sources", tags=["sources"])

_SOURCES = [
    {"id": "entsoe", "name": "ENTSO-E Transparency Platform", "region": "EU", "currency": "EUR"},
    {"id": "elexon", "name": "Elexon Insights Solution (BMRS)", "region": "GB", "currency": "GBP"},
]


@router.get("")
async def list_sources() -> list[dict]:
    return _SOURCES
