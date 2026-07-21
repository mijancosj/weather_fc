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
│   ├── elexon-retriever/     # async REST client for Elexon Insights Solution (BMRS)
│   └── esios-retriever/      # async REST client for ESIOS / Red Eléctrica de España (API token)
├── backend/                  # FastAPI app: orchestrates retrievers, stores in Postgres, serves API
├── frontend/                 # React + Vite + TS dashboard
├── scripts/                  # bootstrap / dev / db-setup helper scripts (PowerShell + bash)
└── docs/                     # architecture notes, Postgres setup, deployment
```

## Why this shape

- **Retrievers are libraries, not services.** `entsoe-retriever`,
  `elexon-retriever`, and `esios-retriever` each expose a small async client +
  pydantic models + an optional local cache. They know nothing about FastAPI,
  Postgres, dashboards, or each other. You can `uv sync` and use any one
  standalone in a notebook or script.
- **The backend composes retrievers, it doesn't own them.** `backend`
  declares all three retrievers as regular dependencies, resolved locally via
  `uv`'s path-source feature (`[tool.uv.sources]`, `editable = true`). Each
  still resolves against its own lockfile independently — this is not a
  shared uv workspace. Adding another data source later means: new sibling
  folder under `data-services/`, one new line in `backend/pyproject.toml`.
- **Every retriever calls its provider's official REST API.**
  `entsoe-retriever` calls the ENTSO-E Transparency Platform's Web API with a
  security token (generated from your account, not your login password) and
  parses its XML response. `elexon-retriever` calls Elexon's Insights
  Solution REST API directly with `httpx`. `esios-retriever` calls REE's
  ESIOS API (`api.esios.ree.es`) with a personal token. None of them drive a
  browser or scrape a webpage — all three go through the method each
  provider actually intends for programmatic access.
- **Cache is a client-level concern, not an architectural commitment.** Every
  retriever client takes a `use_cache` flag per call. Fetch on the fly during
  development, flip caching on once you're hitting rate limits or want
  reproducible historical pulls. The cache is just local Parquet files read
  back through DuckDB — no server, nothing to run.
- **Persistence is Postgres, reached only through the backend, in two
  shapes.** A `prices` table holds money-denominated day-ahead prices,
  normalized the same way across every source. A separate
  `indicator_observations` table holds everything else ESIOS publishes
  (demand, generation by technology, and dozens of other indicators) —
  configurable via `BACKEND_ESIOS_INDICATOR_IDS`, since that data doesn't fit
  the price shape. Both are reached only through SQLAlchemy's async engine,
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

# configure secrets — each package already has a .env checked in with
# dummy/local-only placeholders (see each package's README); just edit them
# in place, no copying needed
# edit entsoe-retriever/.env: set ENTSOE_API_TOKEN (a security token from your
# transparency.entsoe.eu account, not your login password — see that
# package's README for where to generate one)
# edit esios-retriever/.env: set ESIOS_API_TOKEN (request via email — see
# that package's README)
# after editing any .env with a real secret, run:
#   git update-index --skip-worktree <path-to-that-.env>
# so your local edits are never picked up by git status/git add

# set up Postgres (see docs/postgres-setup.md), then:
.\scripts\db-setup.ps1
cd backend; uv run alembic upgrade head; cd ..

# run backend (http://localhost:8000) + frontend (http://localhost:5173)
.\scripts\dev.ps1
```

Bash equivalents (`scripts/bootstrap.sh`, `scripts/db-setup.sh`,
`scripts/dev.sh`) are provided for Git Bash / WSL.

## Deployment

Deployable for free — frontend on Vercel, backend on Render, Postgres on
Neon, with GitHub Actions driving the scheduled data refresh (Render's free
tier suspends idle processes, so an external cron replaces relying on an
always-on scheduler). Full walkthrough: [docs/deployment.md](docs/deployment.md).

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

In-focus markets: **France, Spain, Portugal, and the UK**.

| Source | Package | Coverage | Auth |
| --- | --- | --- | --- |
| ENTSO-E Transparency Platform | `data-services/entsoe-retriever` | FR/ES/PT day-ahead prices + full generation-by-technology mix, per bidding zone (any EIC area, configurable) | API token (free, self-service) |
| Elexon Insights Solution (BMRS) | `data-services/elexon-retriever` | GB market index / system prices (ENTSO-E has no GB data post-Brexit — confirmed live) | Optional API key for higher rate limits |
| ESIOS (Red Eléctrica de España) | `data-services/esios-retriever` | ES day-ahead price + any of ESIOS's other indicators (demand, generation by technology, ...) | Personal token, request via email (free) |

Adding a new ENTSO-E-covered country is a config change
(`BACKEND_ENTSOE_AREAS`), not new code — see
[docs/architecture.md](docs/architecture.md#country-coverage-fr-es-pt-via-entso-e-gb-via-elexon).
Adding an entirely new source follows the retriever-package recipe — see
[docs/architecture.md](docs/architecture.md#adding-a-new-data-source).
