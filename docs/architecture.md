# Architecture

## Goals this structure optimizes for

1. Every Python package must be usable **standalone** — its own
   `pyproject.toml`, its own `uv` venv, its own lockfile, its own tests. You
   should be able to delete every other folder in the repo and still be able
   to `uv sync && uv run pytest` inside `data-services/entsoe-retriever`.
2. The backend composes retrievers as **ordinary dependencies**, not as
   in-repo magic. `uv`'s path/editable sources (`[tool.uv.sources]`) point at
   sibling folders instead of a package index — that's the only thing special
   about how they're wired in.
3. No shared uv workspace. Each `pyproject.toml` is fully self-contained on
   purpose, so a package's dependency resolution never gets pulled sideways
   by an unrelated sibling package's version pins.
4. No Docker anywhere. PostgreSQL runs as a native install locally and a
   managed instance in the cloud; nothing else needs a server process.
5. The frontend has zero awareness of Python or Postgres. It only speaks HTTP
   to `backend`, and could be pointed at a different backend entirely without
   changes beyond `VITE_API_BASE_URL` / the dev proxy target.

## Data flow

```
        ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
        │ ENTSO-E Trans-    │   │ Elexon Insights   │   │ ESIOS (REE)       │
        │ parency Platform  │   │ Solution (BMRS)   │   │ REST API          │
        │ (Web API)         │   │ (REST API)        │   │                   │
        └────────┬─────────┘   └────────┬─────────┘   └────────┬─────────┘
                  │ XML (token)          │ JSON                  │ JSON (token)
                  ▼                      ▼                       ▼
        ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
        │ entsoe-retriever  │   │ elexon-retriever  │   │ esios-retriever   │
        │ (async httpx,     │   │ (async httpx,     │   │ (async httpx,     │
        │  Parquet cache)   │   │  Parquet cache)   │   │  Parquet cache)   │
        └────────┬─────────┘   └────────┬─────────┘   └────────┬─────────┘
                  │  editable path dependency, all three         │
                  └──────────────────────┬────────────────────────┘
                                         ▼
                           ┌────────────────────────────┐
                           │  backend (FastAPI)          │
                           │  - PriceDiscoveryService     │◄── APScheduler tick
                           │    (day-ahead prices,         │    every N minutes
                           │     per-source isolated)      │
                           │  - IndicatorDiscoveryService  │◄── APScheduler tick
                           │    (generic ESIOS indicators,  │    every N minutes
                           │     demand/generation/etc.)     │
                           │  - OutageDiscoveryService      │◄── APScheduler tick
                           │    (generation/transmission     │    every N minutes
                           │     outages, ENTSO-E only)      │
                           │  - PriceRepository /           │
                           │    IndicatorRepository /        │
                           │    OutageRepository            │
                           │    (SQLAlchemy async, Alembic  │
                           │     migrations)                │
                           │  - REST API (/api/v1/...)     │
                           └──────────────┬───────────────┘
                                         │ asyncpg
                                         ▼
                           ┌────────────────────────────┐
                           │  PostgreSQL                  │
                           │  (native install locally,     │
                           │   managed instance in the     │
                           │   cloud)                      │
                           └────────────────────────────┘

                           ┌────────────────────────────┐
backend ───HTTP (JSON)────►│  frontend (React + Vite)     │
(proxied via Vite in dev)  │  TanStack Query + Recharts   │
                           └────────────────────────────┘
```

The frontend only ever talks to `backend`'s REST API — it never touches
Postgres directly, and it has no idea any retriever exists. That's all
backend-internal.

## Every retriever uses its provider's official REST API

None of the retrievers drive a browser or scrape a webpage — all three call
the programmatic access method each provider actually publishes:

- `entsoe-retriever` calls the ENTSO-E Transparency Platform's Web API
  (`https://web-api.tp.entsoe.eu/api`) with a security token
  (`ENTSOE_API_TOKEN`) and parses the returned XML. The token is generated
  from your account (*My Account Settings > Web API Security Token* at
  transparency.entsoe.eu) — it is not your login password.
- `elexon-retriever` calls Elexon's Insights Solution REST API
  (`https://data.elexon.co.uk/bmrs/api/v1`) directly with `httpx` and parses
  the returned JSON. An API key is optional, only needed for a higher rate
  limit.
- `esios-retriever` calls REE's ESIOS API (`https://api.esios.ree.es`) with a
  personal token (`ESIOS_API_TOKEN`, requested by emailing
  consultasios@ree.es) and parses the returned JSON. Unlike the other two,
  ESIOS exposes hundreds of indicators (day-ahead price is just one, ID
  `600`) — `EsiosClient.list_indicators()` is the discovery mechanism, also
  exposed live at `GET /api/v1/indicators/catalog`.

## Country coverage: FR, ES, PT via ENTSO-E; GB via Elexon

The platform's in-focus markets are France, Spain, Portugal, and the UK.
ENTSO-E covers the first three uniformly — `BACKEND_ENTSOE_AREAS` is a list
of EIC codes, and `PriceDiscoveryService`/`IndicatorDiscoveryService` loop
over it, each area isolated in its own `try`/`except` so one country's
outage doesn't block the others.

**GB is deliberately not in that list.** Confirmed against the live API: for
both the day-ahead price and generation-by-type documents, ENTSO-E returns
an explicit `Acknowledgement_MarketDocument` with *"No matching data found"*
for GB — consistent with the UK's post-Brexit departure from the EU's
day-ahead market coupling. This isn't a gap in the client, ENTSO-E genuinely
doesn't have this data for GB. `elexon-retriever` (Elexon's Insights
Solution / BMRS) is GB's real source for price data — there's no UK
equivalent for generation-by-type in this codebase yet (Elexon does publish
a generation-by-fuel-type dataset too, `FUELINST`, just not implemented
here).

Adding a country ENTSO-E does cover: add its EIC code to
`BACKEND_ENTSOE_AREAS` — the frontend's `areas.ts` needs one line too (the
EIC → canonical-code → display-name mapping) to get a color slot and label.

**There is no intraday price data anywhere in this stack, by design.**
Confirmed live against ENTSO-E (even for France, not just GB) — intraday
trading is exchange-level data (EPEX SPOT, OMIE's IDA auctions, N2EX), not
something TSOs publish to ENTSO-E. Spain/Portugal's OMIE intraday sessions
are likely reachable via ESIOS (REE mirrors OMIE data) but unverified as of
2026-07-08 — no `ESIOS_API_TOKEN` has been configured yet to check.

## Trading-relevant fundamentals: forecast vs. actual

Beyond day-ahead price and actual generation, `entsoe-retriever` also
exposes the day-ahead **forecast** for the two things that most drive
short-term price surprises — and `IndicatorDiscoveryService` refreshes both
into `indicator_observations` for every area in `BACKEND_ENTSOE_AREAS`:

- **Wind/solar generation forecast** (`generation_forecast:{psrType}:{area}`)
  vs. actual generation (`generation:{psrType}:{area}`, already there) — a
  large forecast miss on wind/solar is one of the most reliable intraday
  price-movement signals in markets with high renewable penetration.
- **Total system load forecast** (`load:forecast:{area}`) vs. actual
  (`load:actual:{area}`) — the demand-side equivalent.

Both reuse the exact same `GL_MarketDocument` parsing path as actual
generation (`entsoe_retriever.client._iter_gl_points`) — confirmed live that
load, generation, and the wind/solar forecast are all the same document
family, differing only in `documentType`/`processType` and whether a
`MktPSRType` is present.

## Outages: a third table, because the shape is genuinely different

Generation-unit and transmission-asset outages (ENTSO-E document types
`A77`/`A78`) don't fit `prices` (not money) or `indicator_observations` (not
a uniform time series) — they're discrete, revisable event notifications, so
they get their own table: `outage_notifications`
(`backend/src/backend/db/models.py`), served by `OutageRepository` /
`OutageDiscoveryService`, refreshed by two more scheduler jobs
(`_entsoe_generation_outages_job`, `_entsoe_transmission_outages_job`), and
exposed at `GET /api/v1/outages` (filterable by `resource_type`, `area`,
`active_only`).

- **(event_id, revision_number) is the natural key**, not `(area, timestamp)`
  — an outage is amended in place as its status changes (capacity restored,
  dates shifted), and each revision is kept as its own row rather than
  overwritten, so the revision history isn't lost.
- **The full per-minute capacity profile isn't stored point-by-point.**
  `entsoe_retriever.OutageEvent.points` can have dozens of steps (confirmed
  live for transmission outages); for a trading dashboard what matters is
  "how much capacity is out, for how long", so only the min/max available
  capacity across the profile are kept (`min_available_capacity_mw`,
  `max_available_capacity_mw`).
- **ENTSO-E caps outage responses at 200 "instances" per request.**
  Confirmed live: FR alone exceeded this for the default 97-day window
  (7 days back, 90 days ahead) with an HTTP 400 `Acknowledgement_MarketDocument`
  reporting "exceeds the allowed maximum (200)". `OutageDiscoveryService`
  handles this by recursively splitting the window in half and retrying —
  outage density varies unpredictably by country, so this adapts instead of
  guessing a fixed chunk size (see entsoe-retriever's README for the client-side
  quirks: ZIP response body, document-level `Reason`, `Acknowledgement`-as-empty).
- **Interconnector borders are separate config from bidding-zone areas**
  (`BACKEND_ENTSOE_BORDER_PAIRS`, `[in_Domain, out_Domain]` EIC pairs) since
  transmission outages are queried per-border, not per-area. Confirmed live
  for ES-FR and ES-PT; Spain-Morocco is deliberately not included — Morocco
  isn't an ENTSO-E member, so this endpoint has no data for that border.

## Fundamentals split across two tables, by shape not by source

Elexon only ever produces day-ahead prices, so it only ever writes to the
`prices` table. ENTSO-E and ESIOS both produce more than that — the split is
by data shape, not by which source it came from:

- **Day-ahead price** — ENTSO-E's price document and ESIOS's indicator `600`
  are both normalized into the same `prices` table as Elexon (`area`,
  `price_per_mwh`, `currency`) — so price comparison across all three
  markets stays in one place.
- **Everything else** (generation by technology, demand, and whatever else
  ESIOS exposes) goes into a separate `indicator_observations` table
  (`source`, `indicator_id`, `indicator_name`, `geo_id`, `geo_name`,
  `timestamp`, `value`, `unit`) via `IndicatorRepository` /
  `IndicatorDiscoveryService`. ENTSO-E's generation-by-type feed (wind,
  solar, hydro, nuclear, ...) always writes here with `source="entsoe"`,
  `indicator_id` like `generation:B19:10Y1001A1001A82H`. Which *ESIOS*
  indicators to also track is pure configuration —
  `BACKEND_ESIOS_INDICATOR_IDS` — not a code change, since ESIOS has far more
  indicators than anyone will hardcode handling for individually. ENTSO-E's
  generation feed has no equivalent config knob: it always returns every
  production type for the configured area, so there's nothing to select.
- **geo_id is a plain int** (sized for ESIOS's numeric geo scheme) but
  ENTSO-E areas are EIC strings — so ENTSO-E rows fold the area into
  `indicator_id` itself (`generation:{psrType}:{area}`) rather than using
  `geo_id`, and leave `geo_id=0`. Storage technologies (Hydro Pumped
  Storage) additionally suffix `:consumption` since they report generation
  and consumption as separate series for the same timestamp.
- **The repository layer deduplicates by natural key before every upsert**
  (`storage.py`'s `_dedupe_last`) as a safety net: a single multi-row
  `INSERT ... ON CONFLICT DO UPDATE` fails outright in Postgres if two rows
  in the same statement target the same key. This actually happened —
  ENTSO-E's Hydro Pumped Storage generation/consumption split wasn't modeled
  at first, so both collided under one key until it was.

## Per-source failure isolation

`PriceDiscoveryService.refresh()` fetches ENTSO-E, Elexon, and ESIOS
independently, each in its own `try`/`except` — one source having an
expired token or an outage doesn't block the others from being upserted.
Same for `IndicatorDiscoveryService.refresh()`: each configured indicator ID
is fetched independently, so one bad ID doesn't take the rest down.

## Why cache is optional, per-call

Every retriever method takes a `use_cache: bool = True` argument. Nothing in
the architecture forces you to persist anything:

- Set `use_cache=False` everywhere and every call goes straight to the
  upstream API — useful while iterating, or for one-off pulls in a notebook.
- Leave it on (default) and repeated calls for the same window are served
  from a local Parquet file until `*_CACHE_TTL_SECONDS` expires — useful once
  you're polling on a schedule or hitting rate limits.

Postgres, reached through `backend`'s `PriceRepository`, is a separate,
second-tier store: it's not a cache of raw scrape/API responses, it's the
normalized, queryable table the API and dashboard read from. Nothing about
it is local-only — `BACKEND_DATABASE_URL` is just as happy pointing at a
cloud-managed Postgres instance, which is the only change needed to move the
backend's storage to production.

## Adding a new data source

1. `data-services/<name>-retriever/` — copy the shape of `entsoe-retriever`,
   `elexon-retriever`, or `esios-retriever`: `pyproject.toml`,
   `.python-version`,
   `src/<name>_retriever/{__init__,config,models,client,cache,exceptions}.py`,
   `tests/`. Give it its own `uv sync`.
2. In `backend/pyproject.toml`: add `<name>-retriever` to `dependencies`, and
   a matching entry in `[tool.uv.sources]` pointing at the new folder.
3. If it's a price: fetch from the new client in
   `backend/src/backend/services/price_discovery.py`'s `refresh()`, in its
   own `try`/`except` (see "Per-source failure isolation" above), normalize
   its rows to the `prices` table shape, append to `rows`. If it's fundamental
   data that isn't a price (demand, generation, etc.): follow the
   `IndicatorDiscoveryService` pattern instead — normalize to the
   `indicator_observations` shape.
4. Add the source's metadata to `backend/src/backend/api/routes/sources.py`.
5. Nothing in `frontend/` needs to change — it already renders whatever
   `/api/v1/sources` and `/api/v1/prices/day-ahead` return.

## Database schema changes

`prices` and `indicator_observations` (`backend/src/backend/db/models.py`)
are managed by Alembic (`backend/migrations/`). To change either:

1. Edit the SQLAlchemy model in `db/models.py`.
2. `cd backend && uv run alembic revision -m "describe the change"`, fill in
   `upgrade()` / `downgrade()` in the generated file under
   `migrations/versions/`.
3. `uv run alembic upgrade head` locally to apply and verify it.
4. Commit the model change and the migration together.

Never hand-edit the schema directly against a running database — that's
exactly what would drift local/staging/production apart.

## Things intentionally deferred, not designed away

- **Auth / multi-user**: none yet. Add it at the FastAPI layer
  (`backend/src/backend/api/`) when there's more than one consumer of the
  dashboard.
- **Historical backfill**: the scheduler only pulls a rolling 24h window
  right now (`PriceDiscoveryService.refresh`). A backfill job would reuse the
  same clients with a wider `start`/`end` and the same `upsert_prices` path.
- **Alerting / forecasting**: out of scope for the skeleton; the normalized
  `prices` table in Postgres is the natural place for a future forecasting
  package to read from — it would live as another sibling under, e.g.,
  `analytics/price-forecaster/`, same pattern as the retrievers.
- **Repository-level tests against a real Postgres**: not included yet —
  there's no local/CI Postgres wired into the test suite. `services/storage.py`
  documents the query shapes to cover once there is one (e.g. via
  `testcontainers` or a CI-provisioned instance).
