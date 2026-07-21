from datetime import datetime, timezone

import pytest
import respx
from httpx import Response

from esios_retriever.client import EsiosClient
from esios_retriever.config import EsiosSettings
from esios_retriever.exceptions import EsiosConfigurationError

SAMPLE_INDICATOR_PAYLOAD = {
    "indicator": {
        "name": "Precio mercado SPOT Diario",
        "values": [
            {"tz_time": "2026-07-07T00:00:00.000+02:00", "value": 61.5, "geo_id": 3, "geo_name": "España"},
            {"tz_time": "2026-07-07T01:00:00.000+02:00", "value": 58.2, "geo_id": 3, "geo_name": "España"},
        ],
    }
}

SAMPLE_INDICATOR_LIST = {"indicators": [{"id": 600, "name": "Precio mercado SPOT Diario"}]}


@pytest.mark.asyncio
@respx.mock
async def test_get_indicator_parses_values(tmp_path):
    settings = EsiosSettings(api_token="test-token", cache_dir=str(tmp_path))
    respx.get("https://api.esios.ree.es/indicators/600").mock(
        return_value=Response(200, json=SAMPLE_INDICATOR_PAYLOAD)
    )

    async with EsiosClient(settings) as client:
        series = await client.get_indicator(
            600,
            datetime(2026, 7, 7, tzinfo=timezone.utc),
            datetime(2026, 7, 8, tzinfo=timezone.utc),
            use_cache=False,
        )

    assert series.name == "Precio mercado SPOT Diario"
    assert len(series.values) == 2
    assert series.values[0].value == 61.5
    assert series.values[1].geo_name == "España"


@pytest.mark.asyncio
@respx.mock
async def test_list_indicators_parses_summaries(tmp_path):
    settings = EsiosSettings(api_token="test-token", cache_dir=str(tmp_path))
    respx.get("https://api.esios.ree.es/indicators").mock(
        return_value=Response(200, json=SAMPLE_INDICATOR_LIST)
    )

    async with EsiosClient(settings) as client:
        indicators = await client.list_indicators()

    assert len(indicators) == 1
    assert indicators[0].id == 600
    assert indicators[0].name == "Precio mercado SPOT Diario"


@pytest.mark.asyncio
async def test_missing_api_token_raises_configuration_error(tmp_path):
    settings = EsiosSettings(api_token=None, cache_dir=str(tmp_path))

    async with EsiosClient(settings) as client:
        with pytest.raises(EsiosConfigurationError):
            await client.get_indicator(
                600,
                datetime(2026, 7, 7, tzinfo=timezone.utc),
                datetime(2026, 7, 8, tzinfo=timezone.utc),
                use_cache=False,
            )
