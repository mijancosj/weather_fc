from datetime import datetime, timezone

import pytest
import respx
from httpx import Response

from entsoe_retriever.client import EntsoeClient
from entsoe_retriever.config import EntsoeSettings
from entsoe_retriever.exceptions import EntsoeConfigurationError
from entsoe_retriever.models import AreaCode

SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Publication_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3">
  <TimeSeries>
    <Period>
      <timeInterval><start>2026-07-07T00:00Z</start></timeInterval>
      <resolution>PT60M</resolution>
      <Point><position>1</position><price.amount>45.12</price.amount></Point>
      <Point><position>2</position><price.amount>42.80</price.amount></Point>
    </Period>
  </TimeSeries>
</Publication_MarketDocument>"""


@pytest.mark.asyncio
@respx.mock
async def test_get_day_ahead_prices_parses_xml(tmp_path):
    settings = EntsoeSettings(api_token="test-token", cache_dir=str(tmp_path))
    # httpx normalizes a base_url without a trailing slash by adding one when
    # joining with an empty path, so the real request lands on ".../api/".
    respx.get("https://web-api.tp.entsoe.eu/api/").mock(return_value=Response(200, text=SAMPLE_XML))

    async with EntsoeClient(settings) as client:
        series = await client.get_day_ahead_prices(
            AreaCode.DE_LU,
            datetime(2026, 7, 7, tzinfo=timezone.utc),
            datetime(2026, 7, 8, tzinfo=timezone.utc),
            use_cache=False,
        )

    assert len(series.points) == 2
    assert series.points[0].price_eur_mwh == 45.12
    assert series.points[1].price_eur_mwh == 42.80


@pytest.mark.asyncio
async def test_missing_api_token_raises_configuration_error(tmp_path):
    settings = EntsoeSettings(api_token=None, cache_dir=str(tmp_path))

    async with EntsoeClient(settings) as client:
        with pytest.raises(EntsoeConfigurationError):
            await client.get_day_ahead_prices(
                AreaCode.DE_LU,
                datetime(2026, 7, 7, tzinfo=timezone.utc),
                datetime(2026, 7, 8, tzinfo=timezone.utc),
                use_cache=False,
            )
