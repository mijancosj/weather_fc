from datetime import date

import pytest
import respx
from httpx import Response

from elexon_retriever.client import ElexonClient
from elexon_retriever.config import ElexonSettings

SAMPLE_PAYLOAD = [
    {
        "settlementDate": "2026-07-06",
        "settlementPeriod": 1,
        "price": 61.5,
        "volume": 120.0,
        "dataProvider": "APX",
    },
    {
        "settlementDate": "2026-07-06",
        "settlementPeriod": 2,
        "price": 58.2,
        "volume": 110.5,
        "dataProvider": "APX",
    },
]


@pytest.mark.asyncio
@respx.mock
async def test_get_market_index_prices_parses_json(tmp_path):
    settings = ElexonSettings(cache_dir=str(tmp_path))
    respx.get("https://data.elexon.co.uk/bmrs/api/v1/balancing/pricing/market-index").mock(
        return_value=Response(200, json=SAMPLE_PAYLOAD)
    )

    async with ElexonClient(settings) as client:
        series = await client.get_market_index_prices(
            date(2026, 7, 6), date(2026, 7, 6), use_cache=False
        )

    assert len(series.points) == 2
    assert series.points[0].price_gbp_mwh == 61.5
    assert series.points[1].settlement_period == 2
