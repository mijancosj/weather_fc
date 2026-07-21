# backend

FastAPI app that composes `entsoe-retriever`, `elexon-retriever`, and
`esios-retriever` (all REST API clients) into normalized price + indicator
feeds, persists them in Postgres, and serves them to the frontend dashboard.

It depends on the three retriever packages as regular dependencies, resolved
locally via `uv`'s editable path sources (see `[tool.uv.sources]` in
`pyproject.toml`) — each retriever still has its own lockfile and venv when
worked on standalone; the backend just also builds against them.

## Setup

```powershell
uv sync --extra dev
```

`.env` is already checked in with local-dev defaults (Postgres URL) — nothing
to fill in here unless you're pointing at a different database. Make sure
the sibling packages have their own `.env` files filled in too
(`data-services/entsoe-retriever/.env`, `data-services/elexon-retriever/.env`,
`data-services/esios-retriever/.env`) — this process imports and runs their
client code directly.

### Database

Needs a Postgres instance reachable at `BACKEND_DATABASE_URL` (see
[docs/postgres-setup.md](../docs/postgres-setup.md) for a native, docker-free
Windows setup). Once the database exists, apply migrations:

```powershell
uv run alembic upgrade head
```

Schema changes go through Alembic (`migrations/versions/`) — don't hand-edit
the schema; add a new revision with `uv run alembic revision -m "..."`, fill
in `upgrade()`/`downgrade()`, and commit it alongside the `db/models.py`
change it corresponds to.

## Run

```powershell
uv run uvicorn backend.main:app --app-dir src --reload --port 8000
```

(Not `fastapi dev` — its startup banner prints an emoji via `rich`, which
crashes with `UnicodeEncodeError` on a real Windows console using the legacy
`cp1252` codepage. Plain `uvicorn`'s logging doesn't hit that code path.)

- `GET /health` — liveness check
- `GET /api/v1/sources` — configured data sources
- `GET /api/v1/prices/day-ahead?source=entsoe&area=10YFR-RTE------C` — normalized price rows from Postgres (`source` one of `entsoe`, `elexon`, `esios`; `area` an EIC code for entsoe rows, a short code like `GB`/`ES` for elexon/esios rows)
- `GET /api/v1/indicators/catalog` — live list of every indicator ESIOS publishes (discovery — doesn't touch Postgres)
- `GET /api/v1/indicators/{indicator_id}/preview?days=7` — live one-off fetch of a single indicator, doesn't touch Postgres either; check what an indicator looks like before deciding to track it
- `GET /api/v1/indicators/observations?source=entsoe&geo_name=FR` — stored, scheduler-refreshed indicator observations from Postgres, optionally filtered by area (`geo_name`, e.g. `FR`/`ES`/`PT`). Always populated for every area in `BACKEND_ENTSOE_AREAS` with three families of `indicator_id` (see `entsoe-retriever`'s README for the psrType-to-name mapping):
  - `generation:{psrType}:{area}` — actual generation by technology
  - `generation_forecast:{psrType}:{area}` — day-ahead wind/solar forecast
  - `load:forecast:{area}` / `load:actual:{area}` — total system load

  For ESIOS (`source=esios`), only for IDs configured in `BACKEND_ESIOS_INDICATOR_IDS`.

A background job (APScheduler, see `core/scheduler.py`) refreshes Postgres
every `BACKEND_REFRESH_INTERVAL_MINUTES` minutes, via five independent jobs:
day-ahead prices from all sources across every area in `BACKEND_ENTSOE_AREAS`
(default: FR, ES, PT) plus Elexon for GB; ENTSO-E generation-by-type, the
wind/solar forecast, and load (forecast + actual) for the same areas; and
whichever ESIOS indicators are configured in `BACKEND_ESIOS_INDICATOR_IDS`
(empty by default). All the ENTSO-E jobs isolate failures per-area as well
as per-source — one country's fetch failing (rate limit, transient outage)
doesn't block the others.

**GB has no ENTSO-E data** (confirmed live: ENTSO-E returns "No matching
data found" for GB's day-ahead price and generation documents, consistent
with post-Brexit market decoupling) — it's deliberately excluded from
`BACKEND_ENTSOE_AREAS`. Elexon is GB's only source here, and only for
prices; there's no UK generation-by-type source wired up yet.

## Tests

```powershell
uv run pytest
```

`test_health.py` doesn't touch the database — it only exercises the FastAPI
lifespan and the `/health` route. Repository-level tests against a real
Postgres aren't included yet (there's no CI Postgres wired up); see
`services/storage.py` for the query shapes to cover once there is one.
