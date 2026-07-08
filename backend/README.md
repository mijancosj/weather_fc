# backend

FastAPI app that composes `entsoe-retriever` and `elexon-retriever` (both
REST API clients) into one normalized price feed, persists it in Postgres,
and serves it to the frontend dashboard.

It depends on the two retriever packages as regular dependencies, resolved
locally via `uv`'s editable path sources (see `[tool.uv.sources]` in
`pyproject.toml`) — each retriever still has its own lockfile and venv when
worked on standalone; the backend just also builds against them.

## Setup

```powershell
uv sync --extra dev
copy .env.example .env
```

Make sure the sibling packages have their own `.env` files configured too
(`data-services/entsoe-retriever/.env`, `data-services/elexon-retriever/.env`)
— this process imports and runs their client code directly.

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
- `GET /api/v1/prices/day-ahead?source=entsoe&area=10Y1001A1001A82H` — normalized price rows from Postgres

A background job (APScheduler, see `core/scheduler.py`) refreshes Postgres
from both retrievers every `BACKEND_REFRESH_INTERVAL_MINUTES` minutes. A
failed refresh (e.g. a missing/expired API token, an upstream outage) is
logged and skipped — it doesn't crash the API, it just leaves last-known-good
data in place until the next tick.

## Tests

```powershell
uv run pytest
```

`test_health.py` doesn't touch the database — it only exercises the FastAPI
lifespan and the `/health` route. Repository-level tests against a real
Postgres aren't included yet (there's no CI Postgres wired up); see
`services/storage.py` for the query shapes to cover once there is one.
