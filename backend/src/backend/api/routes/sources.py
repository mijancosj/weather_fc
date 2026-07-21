from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/sources", tags=["sources"])

_SOURCES = [
    {"id": "entsoe", "name": "ENTSO-E Transparency Platform", "region": "EU", "currency": "EUR"},
    {"id": "elexon", "name": "Elexon Insights Solution (BMRS)", "region": "GB", "currency": "GBP"},
    {"id": "esios", "name": "ESIOS (Red Eléctrica de España)", "region": "ES", "currency": "EUR"},
]


@router.get("")
async def list_sources() -> list[dict]:
    return _SOURCES
