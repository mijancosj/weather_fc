# Build log: deploying the live instance

This is a record of what actually happened setting up
[weather-fc-orcin.vercel.app](https://weather-fc-orcin.vercel.app/) —
the real sequence of steps and the gotchas hit along the way. For the
clean prescriptive version, see [docs/deployment.md](docs/deployment.md);
this doc is for remembering *why* things are the way they are, and for
redoing this from scratch later without re-discovering the same issues.

## The stack

- **Neon** — Postgres (free tier)
- **Render** — backend (FastAPI, free web service, via `render.yaml`)
- **Vercel** — frontend (static Vite build)
- **GitHub Actions** — cron every 30 min, calls the backend's
  `POST /api/v1/internal/refresh` to trigger a data refresh (see
  "Why the scheduler is split out" in `docs/deployment.md` for the reasoning —
  Render's free tier suspends the process when idle, so an in-process
  scheduler alone can't be trusted).

## Setup order

1. Neon project created, connection string copied.
2. `uv run alembic upgrade head` run locally against Neon to create the schema.
3. Render Blueprint deploy from `render.yaml`, env vars filled in.
4. Vercel project deploy, `VITE_API_BASE_URL` set to the Render URL.
5. Back to Render: `BACKEND_CORS_ORIGINS` set to the Vercel URL, redeployed.
6. GitHub repo secrets (`BACKEND_URL`, `REFRESH_TOKEN`) added for the Actions workflow.

## Problems hit, in the order they came up

### 1. `BACKEND_CORS_ORIGINS` — invalid JSON crashed the backend on boot

Pydantic-settings parses list-typed env vars as JSON. Typing the value as
`[https://your-app.vercel.app]` (missing the inner quotes) instead of
`["https://your-app.vercel.app"]` produces
`pydantic_settings.exceptions.SettingsError: error parsing value for field
"cors_origins"` and the app won't start at all. **Fix:** always include the
quotes inside the brackets for any list-typed `BACKEND_*` env var.

### 2. Neon connection string — `sslmode` vs `ssl`, and pooled vs direct

Neon's dashboard shows a connection string with `?sslmode=require` (and
sometimes `&channel_binding=require`) — that's libpq/psycopg2 syntax. asyncpg
doesn't recognize either parameter name; SQLAlchemy passes unrecognized query
params straight through to asyncpg's `connect()`, so you get
`TypeError: connect() got an unexpected keyword argument 'sslmode'`.

**Fix:** use `?ssl=require` instead, and drop `channel_binding` entirely
(asyncpg has no equivalent parameter — it isn't needed).

Also: Neon's dashboard defaults to showing the **pooled** connection string
(hostname has `-pooler` in it). asyncpg caches prepared statements per
connection, which conflicts with Neon's pooler running in PgBouncer
transaction-pooling mode (can surface as "prepared statement already exists"
errors under load). **Use the direct (non-pooled) connection string instead**
— toggle it in Neon's dashboard next to the connection string. Not needed for
this project's connection volume anyway.

Working format:
```
postgresql+asyncpg://neondb_owner:<password>@<direct-host>.neon.tech/neondb?ssl=require
```

### 3. The refresh endpoint returning 502 from Render

The internal refresh route originally awaited the full `refresh_all()` (many
concurrent ENTSO-E/ESIOS/Elexon calls) before responding. On a cold start
(Render waking the process from sleep), the combined boot + refresh time
exceeded Render's own proxy/gateway timeout, which cuts the connection and
reports a `502` to the caller (GitHub Actions' curl) — this looked like an
application error but wasn't; the backend was still working, just too slow to
answer inside the proxy's window.

**Fix:** the route now kicks off `refresh_all()` as a FastAPI `BackgroundTask`
and returns `202 Accepted` immediately (`backend/api/routes/internal.py`).
Render's idle-suspend window is ~15 minutes, far longer than the background
refresh takes, so the task reliably finishes after the response is sent.
Tradeoff: a successful `202` only confirms the refresh was *triggered*, not
that it *finished* — check Render's logs or query the API to confirm actual
completion.

### 4. Every frontend API call 404ing with a double slash

`VITE_API_BASE_URL` was set in Vercel with a trailing slash
(`https://host.onrender.com/`), and the frontend built the request URL as
`${API_BASE_URL}/api${path}` — producing `https://host.onrender.com//api/...`,
a double slash Render's router treats as a different (non-existent) path.

**Fix:** `frontend/src/api/client.ts` now strips a trailing slash from
`API_BASE_URL` defensively, so it works whether or not the env var has one.

### 5. ENTSO-E 401 / ESIOS 403 — trailing newline in the token

Both `ENTSOE_API_TOKEN` and (separately, later) `ESIOS_API_TOKEN` failed
auth against their real APIs even though the values were otherwise correct.
Visible smoking gun in the request logs: `securityToken=<token>%0A` — a
URL-encoded trailing newline appended to the token. This happens when
copying a token value out of a `.env` file, terminal output, or similar,
and the copy operation grabs the line-ending along with it.

**Fix:** clear the env var field in Render completely, then paste the token
into a plain-text scratch area (Notepad, a browser address bar) first to
confirm the cursor lands immediately after the last character with nothing
following it — *then* copy from there into Render. Re-typing the value by
hand also works and sidesteps the whole class of copy-paste artifact.

### 6. Outage refresh: intermittent `400` responses from ENTSO-E — not a bug

`entsoe_generation_outages_refresh` and `entsoe_transmission_outages_refresh`
show `HTTP/1.1 400` in the logs for some requests, immediately followed by a
second request for half the original date window. **This is expected,
working behavior** — ENTSO-E caps outage-notification responses at 200
"instances" per request, returns a `400` with an "exceeds the allowed
maximum" message when a window is too wide, and
`backend/services/outage_discovery.py`'s adaptive splitting catches exactly
that error and retries with the window halved, recursively, until it fits.
A `400` here only indicates a real problem if it's *not* followed by the
job's `.done` log line — check for `entsoe_generation_outages_refresh.done`
to confirm it ultimately succeeded.

### 7. ESIOS 403 Forbidden — deferred, not solved

`refresh_esios` (day-ahead price for Spain via REE, indicator 600) still
returns `403 Forbidden` as of this writing. Spain's day-ahead price is
already covered via ENTSO-E, so this isn't blocking core functionality —
deferred rather than fixed. Likely cause: either the same trailing-newline
issue on `ESIOS_API_TOKEN`, or the token hasn't actually been approved yet by
REE (requested via emailing consultasios@ree.es, can take ~24h).

## Quick health-check sequence for next time

1. `curl https://<render-url>/health` → should be `200`.
2. Neon SQL Editor: `SELECT count(*) FROM prices;` /
   `indicator_observations` / `outage_notifications` — all should be non-zero
   after at least one successful refresh.
3. GitHub → Actions → run the refresh workflow manually, confirm `202`.
4. Render → Logs → confirm `<job_name>.done` lines with no unexpected
   `.failed` immediately after (the outage jobs' intermediate `400`s during
   window-splitting are normal, see #6 above).
5. Visit the Vercel URL, confirm the dashboard actually renders data.
