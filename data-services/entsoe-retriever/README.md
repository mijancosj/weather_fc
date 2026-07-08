# entsoe-retriever

Async client + local cache for the [ENTSO-E Transparency
Platform](https://transparency.entsoe.eu) REST API. Currently implements
day-ahead auction prices (document type `A44`); the client is structured so
additional document types (load, generation, cross-border flows) are a new
method + XML parser, not a new architecture.

## Setup

```powershell
uv sync --extra dev
copy .env.example .env
# edit .env, set ENTSOE_API_TOKEN
```

`ENTSOE_API_TOKEN` is a security token, not your account password — log in at
transparency.entsoe.eu, then go to *My Account Settings > Web API Security
Token* to request one.

## Usage

```python
import asyncio
from datetime import datetime, timedelta, timezone

from entsoe_retriever import AreaCode, EntsoeClient


async def main() -> None:
    async with EntsoeClient() as client:
        now = datetime.now(timezone.utc)
        series = await client.get_day_ahead_prices(
            AreaCode.DE_LU, now - timedelta(days=1), now
        )
        for point in series.points:
            print(point.timestamp, point.price_eur_mwh)


asyncio.run(main())
```

Pass `use_cache=False` to always hit the live API; leave it on (default) to
read back a local Parquet file via DuckDB when a prior fetch for the same
window is still within `ENTSOE_CACHE_TTL_SECONDS`.

## Tests

```powershell
uv run pytest
```
