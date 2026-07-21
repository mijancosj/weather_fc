from datetime import date, datetime, timezone

import pytest
import respx
from httpx import Response

from elexon_retriever.client import ElexonClient
from elexon_retriever.config import ElexonSettings

# Real shape confirmed against the live API — wrapped in {"metadata", "data"},
# not a bare list (the mocked test previously assumed the latter, which is
# exactly why it never caught this).
SAMPLE_PAYLOAD = {
    "metadata": {"datasets": ["MID"]},
    "data": [
        {
            "startTime": "2026-07-06T00:00:00Z",
            "settlementDate": "2026-07-06",
            "settlementPeriod": 1,
            "price": 61.5,
            "volume": 120.0,
            "dataProvider": "APXMIDP",
        },
        {
            "startTime": "2026-07-06T00:30:00Z",
            "settlementDate": "2026-07-06",
            "settlementPeriod": 2,
            "price": 58.2,
            "volume": 110.5,
            "dataProvider": "APXMIDP",
        },
    ],
}


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
    assert series.points[0].start_time == datetime(2026, 7, 6, 0, 0, tzinfo=timezone.utc)
    assert series.points[1].settlement_period == 2
    assert series.points[1].start_time == datetime(2026, 7, 6, 0, 30, tzinfo=timezone.utc)
    # Distinct start_time per period is the whole point — collapsing all 48
    # settlement periods onto one timestamp (e.g. midnight) would violate
    # the (source, area, timestamp) unique constraint downstream.
    assert series.points[0].start_time != series.points[1].start_time
