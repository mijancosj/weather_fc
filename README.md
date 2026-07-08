# weather_fc — Power Price Discovery Platform

A modular platform for European/GB power price discovery: pull day-ahead and
related market data from multiple grid/market operators, normalize it, store
it in Postgres, and serve dashboards on top of it.

The repo is deliberately **not** a single monolith. Every part that can stand
on its own does: each Python package has its own `pyproject.toml`, its own
`uv`-managed virtual environment, and its own test suite. The frontend is a
fully separate Node/React project. Nothing here uses Docker — Postgres runs
as a native install (locally) or a managed cloud instance (in production),
and nothing else needs a server process to run.

```
weather_fc/
├── data-services/
│   ├── entsoe-retriever/     # async REST client for ENTSO-E Transparency Platform (API token)
│   └── elexon-retriever/     # async REST client for Elexon Insights Solution (BMRS)
├── backend/                  # FastAPI app: orchestrates retrievers, stores in Postgres, serves API
├── frontend/                 # React + Vite + TS dashboard
├── scripts/                  # bootstrap / dev / db-setup helper scripts (PowerShell + bash)
└── docs/                     # architecture notes, Postgres setup
```

## Why this shape

- **Retrievers are libraries, not services.** `entsoe-retriever` and
  `elexon-retriever` each expose a small async client + pydantic models + an
  optional local cache. They know nothing about FastAPI, Postgres, dashboards,
  or each other. You can `uv sync` and use either one standalone in a
  notebook or script.
- **The backend composes retrievers, it doesn't own them.** `backend`
  declares `entsoe-retriever` and `elexon-retriever` as regular dependencies,
  resolved locally via `uv`'s path-source feature (`[tool.uv.sources]`,
  `editable = true`). Each still resolves against its own lockfile
  independently — this is not a shared uv workspace. Adding a third data
  source (e.g. Nord Pool) later means: new sibling folder under
  `data-services/`, one new line in `backend/pyproject.toml`.
- **Both retrievers call official REST APIs.** `entsoe-retriever` calls the
  ENTSO-E Transparency Platform's Web API with a security token (generated
  from your account, not your login password) and parses its XML response.
  `elexon-retriever` calls Elexon's Insights Solution REST API directly with
  `httpx`. Neither drives a browser or scrapes a webpage — both go through
  the method each provider actually intends for programmatic access.
- **Cache is a client-level concern, not an architectural commitment.** Every
  retriever client takes a `use_cache` flag per call. Fetch on the fly during
  development, flip caching on once you're hitting rate limits or want
  reproducible historical pulls. The cache is just local Parquet files read
  back through DuckDB — no server, nothing to run.
- **Persistence is Postgres, reached only through the backend.** The backend
  is the only thing that talks to Postgres — via SQLAlchemy's async engine,
  with schema managed by Alembic migrations. The frontend never touches the
  database directly; it only calls the backend's REST API, which is what
  makes "run this in the cloud" mostly a matter of pointing
  `BACKEND_DATABASE_URL` at a managed instance and deploying `backend` and
  `frontend` wherever you like.
- **The frontend doesn't know Python or Postgres exist.** It talks to
  `backend` over plain HTTP (`/api/v1/...`), proxied through Vite in dev.
  Swap the backend entirely and the frontend doesn't change.

See [docs/architecture.md](docs/architecture.md) for more detail and the
data-flow diagram, and [docs/postgres-setup.md](docs/postgres-setup.md) for
the database setup.

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/) — manages Python versions, venvs, and
  lockfiles for every Python package here. Install once
  (`powershell -c "irm https://astral.sh/uv/install.ps1 | iex"` or via
  `winget install astral-sh.uv`); it will fetch the right Python versions on
  demand.
- Node.js 20+ and npm (already present on this machine: Node 24, npm 11) for
  `frontend/`.
- PostgreSQL, reachable at `BACKEND_DATABASE_URL` — see
  [docs/postgres-setup.md](docs/postgres-setup.md) (native Windows install,
  no Docker).

## Quickstart

```powershell
# one-time setup: creates a venv per Python package + npm install for frontend
.\scripts\bootstrap.ps1

# configure secrets (per package — see each package's .env.example)
copy data-services\entsoe-retriever\.env.example data-services\entsoe-retriever\.env
copy data-services\elexon-retriever\.env.example data-services\elexon-retriever\.env
copy backend\.env.example backend\.env
# edit entsoe-retriever/.env: set ENTSOE_API_TOKEN (a security token from your
# transparency.entsoe.eu account, not your login password — see that
# package's README for where to generate one)

# set up Postgres (see docs/postgres-setup.md), then:
.\scripts\db-setup.ps1
cd backend; uv run alembic upgrade head; cd ..

# run backend (http://localhost:8000) + frontend (http://localhost:5173)
.\scripts\dev.ps1
```

Bash equivalents (`scripts/bootstrap.sh`, `scripts/db-setup.sh`,
`scripts/dev.sh`) are provided for Git Bash / WSL.

## Working on a single package

Every Python package is independent — `cd` into it and use `uv` directly:

```powershell
cd data-services\entsoe-retriever
uv sync --extra dev
uv run pytest
```

```powershell
cd backend
uv sync --extra dev      # also resolves the two local retriever packages
uv run alembic upgrade head
uv run uvicorn backend.main:app --app-dir src --reload --port 8000
```

```powershell
cd frontend
npm install
npm run dev
```

## Data sources

| Source | Package | Coverage | Auth |
| --- | --- | --- | --- |
| ENTSO-E Transparency Platform | `data-services/entsoe-retriever` | EU day-ahead prices, per bidding zone | API token (free, self-service) |
| Elexon Insights Solution (BMRS) | `data-services/elexon-retriever` | GB market index / system prices | Optional API key for higher rate limits |

Adding a new source follows the same recipe both packages use — see
[docs/architecture.md](docs/architecture.md#adding-a-new-data-source).
