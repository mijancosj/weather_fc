# elexon-retriever

Async client + local cache for the [Elexon Insights
Solution](https://bmrs.elexon.co.uk/api-documentation) (BMRS) REST API.
Currently implements GB market index (day-ahead reference) prices; structured
the same way as `entsoe-retriever` so the two stay easy to reason about
side-by-side, without sharing code (each package is meant to be usable
completely on its own).

## Setup

```powershell
uv sync --extra dev
copy .env.example .env
```

An API key is optional for the endpoints this client currently uses.

## Usage

```python
import asyncio
from datetime import date, timedelta

from elexon_retriever import ElexonClient


async def main() -> None:
    async with ElexonClient() as client:
        today = date.today()
        series = await client.get_market_index_prices(today - timedelta(days=1), today)
        for point in series.points:
            print(point.settlement_date, point.settlement_period, point.price_gbp_mwh)


asyncio.run(main())
```

## Tests

```powershell
uv run pytest
```
