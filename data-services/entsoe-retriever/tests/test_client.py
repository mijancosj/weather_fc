import io
import zipfile
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
    # No trailing slash: ENTSO-E's real gateway 404s on ".../api/" (confirmed
    # against the live API) even though httpx's base_url+empty-path join
    # would produce exactly that if the client used base_url — it doesn't,
    # on purpose (see the comment in EntsoeClient.__init__).
    respx.get("https://web-api.tp.entsoe.eu/api").mock(return_value=Response(200, text=SAMPLE_XML))

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


SAMPLE_GENERATION_XML = """<?xml version="1.0" encoding="utf-8"?>
<GL_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-6:generationloaddocument:3:0">
  <TimeSeries>
    <MktPSRType><psrType>B16</psrType></MktPSRType>
    <Period>
      <timeInterval><start>2026-07-07T00:00Z</start></timeInterval>
      <resolution>PT15M</resolution>
      <Point><position>1</position><quantity>0.0</quantity></Point>
      <Point><position>2</position><quantity>12.5</quantity></Point>
    </Period>
  </TimeSeries>
  <TimeSeries>
    <MktPSRType><psrType>B19</psrType></MktPSRType>
    <Period>
      <timeInterval><start>2026-07-07T00:00Z</start></timeInterval>
      <resolution>PT15M</resolution>
      <Point><position>1</position><quantity>1500.2</quantity></Point>
      <Point><position>2</position><quantity>1487.9</quantity></Point>
    </Period>
  </TimeSeries>
  <TimeSeries>
    <MktPSRType><psrType>B10</psrType></MktPSRType>
    <outBiddingZone_Domain.mRID codingScheme="A01">10Y1001A1001A82H</outBiddingZone_Domain.mRID>
    <Period>
      <timeInterval><start>2026-07-07T00:00Z</start></timeInterval>
      <resolution>PT15M</resolution>
      <Point><position>1</position><quantity>200.0</quantity></Point>
    </Period>
  </TimeSeries>
  <TimeSeries>
    <MktPSRType><psrType>B10</psrType></MktPSRType>
    <inBiddingZone_Domain.mRID codingScheme="A01">10Y1001A1001A82H</inBiddingZone_Domain.mRID>
    <Period>
      <timeInterval><start>2026-07-07T00:00Z</start></timeInterval>
      <resolution>PT15M</resolution>
      <Point><position>1</position><quantity>75.0</quantity></Point>
    </Period>
  </TimeSeries>
</GL_MarketDocument>"""


@pytest.mark.asyncio
@respx.mock
async def test_get_generation_by_type_parses_all_production_types(tmp_path):
    settings = EntsoeSettings(api_token="test-token", cache_dir=str(tmp_path))
    respx.get("https://web-api.tp.entsoe.eu/api").mock(
        return_value=Response(200, text=SAMPLE_GENERATION_XML)
    )

    async with EntsoeClient(settings) as client:
        series = await client.get_generation_by_type(
            AreaCode.DE_LU,
            datetime(2026, 7, 7, tzinfo=timezone.utc),
            datetime(2026, 7, 8, tzinfo=timezone.utc),
            use_cache=False,
        )

    assert len(series.points) == 6
    solar_points = [p for p in series.points if p.psr_type == "B16"]
    wind_points = [p for p in series.points if p.psr_type == "B19"]
    pumped_storage_points = [p for p in series.points if p.psr_type == "B10"]
    generation_point = next(p for p in pumped_storage_points if not p.is_consumption)
    consumption_point = next(p for p in pumped_storage_points if p.is_consumption)
    # outBiddingZone_Domain marks the consumption (pumping) side; every
    # pure-generation TimeSeries — including the other one here — uses
    # inBiddingZone_Domain instead (see the comment in client.py).
    assert consumption_point.quantity_mw == 200.0
    assert generation_point.quantity_mw == 75.0
    assert len(solar_points) == 2
    assert len(wind_points) == 2
    assert wind_points[0].quantity_mw == 1500.2
    assert solar_points[1].resolution_minutes == 15


SAMPLE_LOAD_XML = """<?xml version="1.0" encoding="utf-8"?>
<GL_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-6:generationloaddocument:3:0">
  <TimeSeries>
    <outBiddingZone_Domain.mRID codingScheme="A01">10YFR-RTE------C</outBiddingZone_Domain.mRID>
    <Period>
      <timeInterval><start>2026-07-08T20:00Z</start></timeInterval>
      <resolution>PT15M</resolution>
      <Point><position>1</position><quantity>50800</quantity></Point>
      <Point><position>2</position><quantity>51650</quantity></Point>
    </Period>
  </TimeSeries>
</GL_MarketDocument>"""


@pytest.mark.asyncio
@respx.mock
async def test_get_load_forecast_parses_xml(tmp_path):
    settings = EntsoeSettings(api_token="test-token", cache_dir=str(tmp_path))
    respx.get("https://web-api.tp.entsoe.eu/api").mock(
        return_value=Response(200, text=SAMPLE_LOAD_XML)
    )

    async with EntsoeClient(settings) as client:
        series = await client.get_load_forecast(
            AreaCode.FR,
            datetime(2026, 7, 8, tzinfo=timezone.utc),
            datetime(2026, 7, 9, tzinfo=timezone.utc),
            use_cache=False,
        )

    assert series.is_forecast is True
    assert len(series.points) == 2
    assert series.points[0].load_mw == 50800
    assert series.points[1].load_mw == 51650


@pytest.mark.asyncio
@respx.mock
async def test_get_load_actual_parses_xml_and_sets_is_forecast_false(tmp_path):
    settings = EntsoeSettings(api_token="test-token", cache_dir=str(tmp_path))
    respx.get("https://web-api.tp.entsoe.eu/api").mock(
        return_value=Response(200, text=SAMPLE_LOAD_XML)
    )

    async with EntsoeClient(settings) as client:
        series = await client.get_load_actual(
            AreaCode.FR,
            datetime(2026, 7, 8, tzinfo=timezone.utc),
            datetime(2026, 7, 9, tzinfo=timezone.utc),
            use_cache=False,
        )

    assert series.is_forecast is False
    assert len(series.points) == 2


@pytest.mark.asyncio
@respx.mock
async def test_get_wind_solar_forecast_reuses_generation_parsing(tmp_path):
    settings = EntsoeSettings(api_token="test-token", cache_dir=str(tmp_path))
    respx.get("https://web-api.tp.entsoe.eu/api").mock(
        return_value=Response(200, text=SAMPLE_GENERATION_XML)
    )

    async with EntsoeClient(settings) as client:
        series = await client.get_wind_solar_forecast(
            AreaCode.DE_LU,
            datetime(2026, 7, 7, tzinfo=timezone.utc),
            datetime(2026, 7, 8, tzinfo=timezone.utc),
            use_cache=False,
        )

    # Same GL document family/parser as get_generation_by_type — the sample
    # here happens to also include pumped-storage psr types, which is fine
    # for exercising the shared parsing path.
    assert len(series.points) == 6


# Trimmed from a real live response (see entsoe-retriever README) — one
# TimeSeries with Reason as a document-level sibling, not nested inside
# TimeSeries like every other document family here.
SAMPLE_GENERATION_OUTAGE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Unavailability_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-6:outagedocument:3:0">
  <mRID>atz97gnTtXITHXpcaB3W6A</mRID>
  <revisionNumber>2</revisionNumber>
  <unavailability_Time_Period.timeInterval>
    <start>2025-12-31T23:00Z</start>
    <end>2026-08-13T22:00Z</end>
  </unavailability_Time_Period.timeInterval>
  <TimeSeries>
    <mRID>1</mRID>
    <businessType>A53</businessType>
    <biddingZone_Domain.mRID codingScheme="A01">10YES-REE------0</biddingZone_Domain.mRID>
    <production_RegisteredResource.mRID codingScheme="A01">18WDUEB-12345-0Z</production_RegisteredResource.mRID>
    <production_RegisteredResource.name>DUERO B</production_RegisteredResource.name>
    <production_RegisteredResource.location.name>Spain</production_RegisteredResource.location.name>
    <production_RegisteredResource.pSRType.psrType>B10</production_RegisteredResource.pSRType.psrType>
    <production_RegisteredResource.pSRType.powerSystemResources.nominalP unit="MAW">1308.0</production_RegisteredResource.pSRType.powerSystemResources.nominalP>
    <Available_Period>
      <timeInterval>
        <start>2025-12-31T23:00Z</start>
        <end>2026-08-13T22:00Z</end>
      </timeInterval>
      <resolution>PT1M</resolution>
      <Point><position>1</position><quantity>1170</quantity></Point>
    </Available_Period>
  </TimeSeries>
  <Reason>
    <code>A95</code>
  </Reason>
</Unavailability_MarketDocument>"""

SAMPLE_TRANSMISSION_OUTAGE_XML = """<?xml version="1.0" encoding="utf-8"?>
<Unavailability_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-6:outagedocument:3:0">
  <mRID>6DlwBO7afWqPBp_PrMhtgg</mRID>
  <revisionNumber>1</revisionNumber>
  <unavailability_Time_Period.timeInterval>
    <start>2026-06-15T06:00Z</start>
    <end>2026-06-15T08:00Z</end>
  </unavailability_Time_Period.timeInterval>
  <TimeSeries>
    <mRID>1</mRID>
    <businessType>A53</businessType>
    <in_Domain.mRID codingScheme="A01">10YES-REE------0</in_Domain.mRID>
    <out_Domain.mRID codingScheme="A01">10YFR-RTE------C</out_Domain.mRID>
    <Available_Period>
      <timeInterval>
        <start>2026-06-15T06:00Z</start>
        <end>2026-06-15T08:00Z</end>
      </timeInterval>
      <resolution>PT1M</resolution>
      <Point><position>1</position><quantity>1800</quantity></Point>
      <Point><position>61</position><quantity>2150</quantity></Point>
    </Available_Period>
  </TimeSeries>
  <Reason>
    <code>A95</code>
    <text>Outaged line due to maintenance work</text>
  </Reason>
</Unavailability_MarketDocument>"""

SAMPLE_ACKNOWLEDGEMENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Acknowledgement_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-1:acknowledgementdocument:7:0">
  <Reason><code>999</code><text>No matching data found</text></Reason>
</Acknowledgement_MarketDocument>"""


def _zip_of(*xml_bodies: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for i, body in enumerate(xml_bodies):
            zf.writestr(f"{i:03d}-OUTAGE.xml", body)
    return buffer.getvalue()


@pytest.mark.asyncio
@respx.mock
async def test_get_generation_outages_parses_zip(tmp_path):
    settings = EntsoeSettings(api_token="test-token", cache_dir=str(tmp_path))
    respx.get("https://web-api.tp.entsoe.eu/api").mock(
        return_value=Response(200, content=_zip_of(SAMPLE_GENERATION_OUTAGE_XML))
    )

    async with EntsoeClient(settings) as client:
        events = await client.get_generation_outages(
            AreaCode.ES,
            datetime(2025, 12, 31, tzinfo=timezone.utc),
            datetime(2026, 8, 14, tzinfo=timezone.utc),
        )

    assert len(events) == 1
    event = events[0]
    assert event.event_id == "atz97gnTtXITHXpcaB3W6A"
    assert event.revision_number == 2
    assert event.resource_type == "generation"
    assert event.business_type == "A53"
    assert event.reason_code == "A95"
    assert event.unit_name == "DUERO B"
    assert event.psr_type == "B10"
    assert event.nominal_capacity_mw == 1308.0
    assert len(event.points) == 1
    assert event.points[0].available_capacity_mw == 1170.0


@pytest.mark.asyncio
@respx.mock
async def test_get_transmission_outages_parses_stepped_capacity_profile(tmp_path):
    settings = EntsoeSettings(api_token="test-token", cache_dir=str(tmp_path))
    respx.get("https://web-api.tp.entsoe.eu/api").mock(
        return_value=Response(200, content=_zip_of(SAMPLE_TRANSMISSION_OUTAGE_XML))
    )

    async with EntsoeClient(settings) as client:
        events = await client.get_transmission_outages(
            AreaCode.ES,
            AreaCode.FR,
            datetime(2026, 6, 15, tzinfo=timezone.utc),
            datetime(2026, 6, 16, tzinfo=timezone.utc),
        )

    assert len(events) == 1
    event = events[0]
    assert event.resource_type == "transmission"
    assert event.in_area == "10YES-REE------0"
    assert event.out_area == "10YFR-RTE------C"
    assert event.area is None
    assert event.reason_code == "A95"
    # Two Point entries at PT1M resolution — a stepped capacity profile,
    # not one flat value for the whole outage (confirmed against real data).
    assert len(event.points) == 2
    assert event.points[0].available_capacity_mw == 1800.0
    assert event.points[1].available_capacity_mw == 2150.0
    assert event.points[1].timestamp == datetime(2026, 6, 15, 7, 0)


@pytest.mark.asyncio
@respx.mock
async def test_get_generation_outages_returns_empty_on_acknowledgement(tmp_path):
    """No outages in the requested window: ENTSO-E returns a plain
    Acknowledgement_MarketDocument XML instead of a ZIP — not an error.
    """
    settings = EntsoeSettings(api_token="test-token", cache_dir=str(tmp_path))
    respx.get("https://web-api.tp.entsoe.eu/api").mock(
        return_value=Response(200, text=SAMPLE_ACKNOWLEDGEMENT_XML)
    )

    async with EntsoeClient(settings) as client:
        events = await client.get_generation_outages(
            AreaCode.GB,
            datetime(2026, 7, 7, tzinfo=timezone.utc),
            datetime(2026, 7, 8, tzinfo=timezone.utc),
        )

    assert events == []


# Trimmed from a real live response — Publication_MarketDocument v7:0
# (confirmed live to be a distinct namespace version from the day-ahead
# price document's v7:3), keyed by in_Domain/out_Domain rather than area.
SAMPLE_FLOW_XML = """<?xml version="1.0" encoding="utf-8"?>
<Publication_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:0">
  <TimeSeries>
    <businessType>A66</businessType>
    <in_Domain.mRID codingScheme="A01">10YES-REE------0</in_Domain.mRID>
    <out_Domain.mRID codingScheme="A01">10YFR-RTE------C</out_Domain.mRID>
    <Period>
      <timeInterval><start>2026-07-08T07:45Z</start></timeInterval>
      <resolution>PT15M</resolution>
      <Point><position>1</position><quantity>1485.2</quantity></Point>
      <Point><position>2</position><quantity>1579.16</quantity></Point>
    </Period>
  </TimeSeries>
</Publication_MarketDocument>"""

# ATC (A61) shares the same document shape as flows (A11) but confirmed
# live to have sparse point positions — a value holds until the next
# explicit point rather than every position being listed.
SAMPLE_ATC_XML = """<?xml version="1.0" encoding="utf-8"?>
<Publication_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:0">
  <TimeSeries>
    <businessType>A27</businessType>
    <in_Domain.mRID codingScheme="A01">10YFR-RTE------C</in_Domain.mRID>
    <out_Domain.mRID codingScheme="A01">10YES-REE------0</out_Domain.mRID>
    <Period>
      <timeInterval><start>2026-07-09T07:00Z</start></timeInterval>
      <resolution>PT60M</resolution>
      <Point><position>1</position><quantity>2790</quantity></Point>
      <Point><position>3</position><quantity>1050</quantity></Point>
    </Period>
  </TimeSeries>
</Publication_MarketDocument>"""

SAMPLE_INSTALLED_CAPACITY_XML = """<?xml version="1.0" encoding="utf-8"?>
<GL_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-6:generationloaddocument:3:0">
  <TimeSeries>
    <businessType>A37</businessType>
    <inBiddingZone_Domain.mRID codingScheme="A01">10YES-REE------0</inBiddingZone_Domain.mRID>
    <MktPSRType><psrType>B01</psrType></MktPSRType>
    <Period>
      <timeInterval><start>2025-12-31T23:00Z</start></timeInterval>
      <resolution>P1Y</resolution>
      <Point><position>1</position><quantity>753.4</quantity></Point>
    </Period>
  </TimeSeries>
  <TimeSeries>
    <businessType>A37</businessType>
    <inBiddingZone_Domain.mRID codingScheme="A01">10YES-REE------0</inBiddingZone_Domain.mRID>
    <MktPSRType><psrType>B04</psrType></MktPSRType>
    <Period>
      <timeInterval><start>2025-12-31T23:00Z</start></timeInterval>
      <resolution>P1Y</resolution>
      <Point><position>1</position><quantity>29920.8</quantity></Point>
    </Period>
  </TimeSeries>
</GL_MarketDocument>"""

# A71's TimeSeries has no MktPSRType (aggregate across every technology) and
# tags itself with outBiddingZone_Domain — confirmed live this is NOT the
# same "is_consumption" signal that outBiddingZone_Domain means for
# generation-by-type's pumped-storage split.
SAMPLE_AGGREGATED_FORECAST_XML = """<?xml version="1.0" encoding="utf-8"?>
<GL_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-6:generationloaddocument:3:0">
  <TimeSeries>
    <businessType>A01</businessType>
    <outBiddingZone_Domain.mRID codingScheme="A01">10YES-REE------0</outBiddingZone_Domain.mRID>
    <Period>
      <timeInterval><start>2026-07-09T07:45Z</start></timeInterval>
      <resolution>PT15M</resolution>
      <Point><position>1</position><quantity>1772</quantity></Point>
      <Point><position>2</position><quantity>1306</quantity></Point>
    </Period>
  </TimeSeries>
</GL_MarketDocument>"""


@pytest.mark.asyncio
@respx.mock
async def test_get_cross_border_flows_parses_xml(tmp_path):
    settings = EntsoeSettings(api_token="test-token", cache_dir=str(tmp_path))
    respx.get("https://web-api.tp.entsoe.eu/api").mock(return_value=Response(200, text=SAMPLE_FLOW_XML))

    async with EntsoeClient(settings) as client:
        series = await client.get_cross_border_flows(
            AreaCode.ES,
            AreaCode.FR,
            datetime(2026, 7, 8, tzinfo=timezone.utc),
            datetime(2026, 7, 9, tzinfo=timezone.utc),
            use_cache=False,
        )

    assert series.area_in == "10YES-REE------0"
    assert series.area_out == "10YFR-RTE------C"
    assert len(series.points) == 2
    assert series.points[0].flow_mw == 1485.2
    assert series.points[1].flow_mw == 1579.16


@pytest.mark.asyncio
@respx.mock
async def test_get_transfer_capacity_parses_sparse_points(tmp_path):
    settings = EntsoeSettings(api_token="test-token", cache_dir=str(tmp_path))
    respx.get("https://web-api.tp.entsoe.eu/api").mock(return_value=Response(200, text=SAMPLE_ATC_XML))

    async with EntsoeClient(settings) as client:
        series = await client.get_transfer_capacity(
            AreaCode.FR,
            AreaCode.ES,
            datetime(2026, 7, 9, tzinfo=timezone.utc),
            datetime(2026, 7, 10, tzinfo=timezone.utc),
            use_cache=False,
        )

    assert len(series.points) == 2
    assert series.points[0].capacity_mw == 2790
    # Position 3 with PT60M resolution -> 2 hours after period start,
    # confirming sparse (non-contiguous) positions parse correctly.
    assert series.points[1].timestamp == datetime(2026, 7, 9, 9, 0)
    assert series.points[1].capacity_mw == 1050


@pytest.mark.asyncio
@respx.mock
async def test_get_installed_capacity_parses_per_technology(tmp_path):
    settings = EntsoeSettings(api_token="test-token", cache_dir=str(tmp_path))
    respx.get("https://web-api.tp.entsoe.eu/api").mock(
        return_value=Response(200, text=SAMPLE_INSTALLED_CAPACITY_XML)
    )

    async with EntsoeClient(settings) as client:
        series = await client.get_installed_capacity(AreaCode.ES, 2026, use_cache=False)

    assert len(series.points) == 2
    biomass = next(p for p in series.points if p.psr_type == "B01")
    gas = next(p for p in series.points if p.psr_type == "B04")
    assert biomass.capacity_mw == 753.4
    assert gas.capacity_mw == 29920.8


@pytest.mark.asyncio
@respx.mock
async def test_get_generation_forecast_aggregated_parses_xml(tmp_path):
    settings = EntsoeSettings(api_token="test-token", cache_dir=str(tmp_path))
    respx.get("https://web-api.tp.entsoe.eu/api").mock(
        return_value=Response(200, text=SAMPLE_AGGREGATED_FORECAST_XML)
    )

    async with EntsoeClient(settings) as client:
        series = await client.get_generation_forecast_aggregated(
            AreaCode.ES,
            datetime(2026, 7, 9, tzinfo=timezone.utc),
            datetime(2026, 7, 10, tzinfo=timezone.utc),
            use_cache=False,
        )

    assert len(series.points) == 2
    assert series.points[0].forecast_mw == 1772
    assert series.points[1].forecast_mw == 1306


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
