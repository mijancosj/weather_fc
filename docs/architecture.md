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
                      ┌─────────────────────┐        ┌─────────────────────┐
                      │  ENTSO-E Trans-       │        │  Elexon Insights    │
                      │  parency Platform     │        │  Solution (BMRS)    │
                      │  (Web API)            │        │  (REST API)         │
                      └──────────┬──────────┘        └──────────┬──────────┘
                                 │ XML (security token)           │ JSON (REST API)
                                 ▼                                ▼
                    ┌────────────────────────┐        ┌────────────────────────┐
                    │  entsoe-retriever      │        │  elexon-retriever      │
                    │  (async httpx client,  │        │  (async httpx client,  │
                    │  pydantic models,      │        │  pydantic models,      │
                    │  optional Parquet      │        │  optional Parquet      │
                    │  cache via DuckDB)     │        │  cache via DuckDB)     │
                    └───────────┬────────────┘        └───────────┬────────────┘
                                │  editable path dependency          │
                                └───────────────┬─────────────────────┘
                                                ▼
                                  ┌───────────────────────────┐
                                  │  backend (FastAPI)         │
                                  │  - PriceDiscoveryService    │◄── APScheduler tick
                                  │    normalizes + merges      │    every N minutes
                                  │  - PriceRepository           │
                                  │    (SQLAlchemy async, Alembic│
                                  │     migrations)              │
                                  │  - REST API (/api/v1/...)   │
                                  └──────────────┬──────────────┘
                                                │ asyncpg
                                                ▼
                                  ┌───────────────────────────┐
                                  │  PostgreSQL                │
                                  │  (native install locally,  │
                                  │   managed instance in the  │
                                  │   cloud)                   │
                                  └───────────────────────────┘

                                  ┌───────────────────────────┐
backend ───────HTTP (JSON)──────►│  frontend (React + Vite)   │
(proxied via Vite in dev)        │  TanStack Query + Recharts │
                                  └───────────────────────────┘
```

The frontend only ever talks to `backend`'s REST API — it never touches
Postgres directly, and it has no idea either retriever exists. That's all
backend-internal.

## Both retrievers use official REST APIs

Neither retriever drives a browser or scrapes a webpage — both call the
programmatic access method each provider actually publishes:

- `entsoe-retriever` calls the ENTSO-E Transparency Platform's Web API
  (`https://web-api.tp.entsoe.eu/api`) with a security token
  (`ENTSOE_API_TOKEN`) and parses the returned XML. The token is generated
  from your account (*My Account Settings > Web API Security Token* at
  transparency.entsoe.eu) — it is not your login password.
- `elexon-retriever` calls Elexon's Insights Solution REST API
  (`https://data.elexon.co.uk/bmrs/api/v1`) directly with `httpx` and parses
  the returned JSON. An API key is optional, only needed for a higher rate
  limit.

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

1. `data-services/<name>-retriever/` — copy the shape of `entsoe-retriever`
   or `elexon-retriever`: `pyproject.toml`, `.python-version`,
   `src/<name>_retriever/{__init__,config,models,client,cache,exceptions}.py`,
   `tests/`. Give it its own `uv sync`.
2. In `backend/pyproject.toml`: add `<name>-retriever` to `dependencies`, and
   a matching entry in `[tool.uv.sources]` pointing at the new folder.
3. In `backend/src/backend/services/price_discovery.py`: fetch from the new
   client in `refresh()`, normalize its rows to the `prices` table shape
   (`source`, `area`, `timestamp`, `price_per_mwh`, `currency`), append them
   to `rows`.
4. Add the source's metadata to `backend/src/backend/api/routes/sources.py`.
5. Nothing in `frontend/` needs to change — it already renders whatever
   `/api/v1/sources` and `/api/v1/prices/day-ahead` return.

## Database schema changes

The `prices` table (`backend/src/backend/db/models.py`) is managed by
Alembic (`backend/migrations/`). To change it:

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
