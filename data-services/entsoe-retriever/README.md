# entsoe-retriever

Async client + local cache for the [ENTSO-E Transparency
Platform](https://transparency.entsoe.eu) REST API. Implements:

- **Day-ahead auction prices** (document type `A44`)
- **Actual generation per production type** (document type `A75`, process
  type `A16`) — wind, solar, hydro, nuclear, fossil, and every other
  technology ENTSO-E reports for a bidding zone, all in one call
- **Wind/solar generation forecast** (document type `A69`, process type
  `A01`) — same shape as actual generation (`GenerationSeries`); diffing
  this against actual generation for the same window is the classic
  forecast-error trading signal
- **Total system load — forecast and actual** (document type `A65`,
  process types `A01`/`A16`) — the demand-side equivalent: diffing forecast
  vs. actual is a classic demand-surprise signal
- **Generation-unit and transmission-asset outages** (document types `A77`/
  `A78`) — planned maintenance and forced unavailability notifications, often
  the single biggest short-term price mover. A fundamentally different
  response shape from everything else here: a ZIP archive of discrete,
  revisable event documents, not a uniform time series (see below)

All verified against the live API, not just mocked responses — see the
notes below on quirks that only showed up there. There is deliberately no
intraday price method: ENTSO-E's Transparency Platform doesn't publish
intraday market prices at all (confirmed live — even for France, not just
GB), that's exchange-level data (EPEX SPOT, OMIE, ...), not TSO data.

## Setup

```powershell
uv sync --extra dev
# edit .env (already checked in with a dummy placeholder), set ENTSOE_API_TOKEN
```

After pasting a real token, run `git update-index --skip-worktree .env` so
your local edit is never picked up by `git status`/`git add`.

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

        prices = await client.get_day_ahead_prices(
            AreaCode.DE_LU, now - timedelta(days=1), now
        )
        for point in prices.points:
            print(point.timestamp, point.price_eur_mwh)

        generation = await client.get_generation_by_type(
            AreaCode.DE_LU, now - timedelta(days=1), now
        )
        for point in generation.points:
            if point.psr_type == "B19":  # Wind Onshore
                print(point.timestamp, point.quantity_mw)

        # Forecast vs. actual for the same window — the classic trading signal
        forecast = await client.get_wind_solar_forecast(
            AreaCode.DE_LU, now - timedelta(days=1), now
        )

        load_forecast = await client.get_load_forecast(
            AreaCode.DE_LU, now, now + timedelta(days=1)  # forecast, so the future
        )
        load_actual = await client.get_load_actual(
            AreaCode.DE_LU, now - timedelta(days=1), now
        )

        # Outages: planned maintenance + forced unavailability. Not cached —
        # revisions supersede in place and staleness here is a real trading risk.
        generation_outages = await client.get_generation_outages(
            AreaCode.ES, now - timedelta(days=7), now + timedelta(days=90)
        )
        transmission_outages = await client.get_transmission_outages(
            AreaCode.ES, AreaCode.FR, now - timedelta(days=7), now + timedelta(days=90)
        )


asyncio.run(main())
```

`GenerationSeries.points` is one flat list spanning every production type
ENTSO-E returned — filter by `psr_type` (see `PSR_TYPE_NAMES` for the
code-to-name mapping, e.g. `B16` = Solar, `B18`/`B19` = Wind Offshore/Onshore).

Storage technologies (currently just Hydro Pumped Storage, `B10`) report
**two** series per timestamp: energy generated (discharging) and energy
consumed (pumping/charging). `GenerationValue.is_consumption` distinguishes
them — every other production type is generation-only and always has
`is_consumption=False`.

Pass `use_cache=False` to always hit the live API; leave it on (default) to
read back a local Parquet file via DuckDB when a prior fetch for the same
window is still within `ENTSOE_CACHE_TTL_SECONDS`.

### Outages are a different shape than everything else

`get_generation_outages`/`get_transmission_outages` return `list[OutageEvent]`,
not a `*Series` with a flat `points` list — outages are discrete, revisable
notifications (identified by `event_id` + `revision_number`), each with its
own declared period and an `Available_Period` capacity profile
(`OutageEvent.points`), confirmed live to sometimes step mid-outage (partial
capacity restored partway through) rather than stay flat. Confirmed live
quirks specific to this endpoint:

- **The response body is a ZIP archive**, not XML — one
  `Unavailability_MarketDocument` per outage notification, unzipped and
  parsed individually (`_parse_outage_zip`).
- **`Reason` is a document-level sibling of `TimeSeries`**, not nested inside
  it like every other document family here — one reason for the whole
  notification.
- **ENTSO-E caps responses at 200 "instances" per request** and returns an
  HTTP 400 (not 200) with an `Acknowledgement_MarketDocument` body when
  exceeded — confirmed live for FR's generation outages over a 97-day
  window. The backend's `OutageDiscoveryService` handles this by splitting
  the requested window in half and retrying recursively until each half
  fits, since outage density varies unpredictably by country and isn't
  worth guessing a fixed chunk size for.
- **A genuine "no outages in this window" response is a plain
  `Acknowledgement_MarketDocument` XML**, not a ZIP — `_parse_outage_zip`
  detects this and returns `[]` rather than raising.

## Things that only surfaced against the real API

- **No trailing slash on the base URL.** `httpx`'s `base_url` + empty-path
  join normalizes to `.../api/`, and ENTSO-E's real gateway 404s on that
  exact variant while accepting `.../api` — the client passes the full URL
  explicitly on every request instead of relying on `base_url` join (see
  the comment in `EntsoeClient.__init__`).
- **`.env` resolves relative to this package, not the caller's cwd.**
  `EntsoeSettings`' `env_file` points at this package's own directory
  (`_PACKAGE_ROOT / ".env"`), not a bare `".env"` — otherwise, embedded in
  `backend` (which runs with a different cwd), the token would silently
  never be found.
- **Hydro Pumped Storage direction.** `outBiddingZone_Domain.mRID` marks the
  consumption/pumping side; every pure-generation TimeSeries (Biomass, Wind,
  Solar, ...) uses `inBiddingZone_Domain.mRID` instead — easy to get backwards
  (this repo did, once) since both attributes sound generation-adjacent.

## Tests

```powershell
uv run pytest
```
