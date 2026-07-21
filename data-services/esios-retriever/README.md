# esios-retriever

Async client + local cache for the [ESIOS](https://www.esios.ree.es) public
REST API (`api.esios.ree.es`), operated by Red Eléctrica de España (REE).
Covers day-ahead prices, demand, generation by technology, and many other
Spanish power market indicators — each identified by a numeric indicator ID.

## Setup

```powershell
uv sync --extra dev
copy .env.example .env
```

`ESIOS_API_TOKEN` is a personal token, requested by emailing
**consultasios@ree.es** with subject line `Personal token request` and your
registered email in the body. Usually granted within ~24h, free.

## Finding indicator IDs

ESIOS has hundreds of indicators. Use `list_indicators()` to search/browse
them, or check a known one directly:

```python
import asyncio
from esios_retriever import EsiosClient

async def main() -> None:
    async with EsiosClient() as client:
        indicators = await client.list_indicators()
        for i in indicators:
            if "precio" in i.name.lower():
                print(i.id, i.name)

asyncio.run(main())
```

A few commonly used ones:

| ID | Name | What it is |
| --- | --- | --- |
| `600` | Precio mercado SPOT Diario | Day-ahead market price (`EsiosClient.DAY_AHEAD_PRICE_INDICATOR_ID`) |

Add more to this table as you identify the indicators your analysis needs —
`list_indicators()` is the source of truth, not this list.

## Usage

```python
import asyncio
from datetime import datetime, timedelta, timezone

from esios_retriever import EsiosClient
from esios_retriever.client import DAY_AHEAD_PRICE_INDICATOR_ID


async def main() -> None:
    async with EsiosClient() as client:
        now = datetime.now(timezone.utc)
        series = await client.get_indicator(
            DAY_AHEAD_PRICE_INDICATOR_ID, now - timedelta(days=1), now
        )
        for point in series.values:
            print(point.timestamp, point.value)


asyncio.run(main())
```

`get_indicator` also takes `geo_ids` (filter by geographic scope — e.g. by
region/country when an indicator covers more than one) and `time_trunc`
(`hour`, `day`, `month`, `year` — the aggregation granularity ESIOS returns).
Pass `use_cache=False` to always hit the live API; leave it on (default) to
read back a local Parquet file via DuckDB when a prior fetch for the same
indicator/window is still within `ESIOS_CACHE_TTL_SECONDS`.

## Tests

```powershell
uv run pytest
```
