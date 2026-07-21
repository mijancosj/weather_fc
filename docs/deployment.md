# Deploying for free

Four pieces, each on its own free tier, chosen specifically so the one thing
that actually matters here — the scheduled data refresh — doesn't silently
stop working when a free host suspends an idle process.

```
Vercel (frontend, static)  ──HTTP──►  Render (backend, FastAPI)  ──►  Neon (Postgres)
                                              ▲
                                              │ POST /api/v1/internal/refresh
                                              │ (X-Refresh-Token header)
                                     GitHub Actions (cron, every 30 min)
```

## Why this split

Render's (and most other) free web-service tiers suspend the process after
~15 minutes with no HTTP traffic. That's fine for serving the dashboard's API
on demand (a few seconds of cold-start on the first request after a while),
but it means the backend's own in-process APScheduler
(`backend/core/scheduler.py`) can't be trusted to tick every
`BACKEND_REFRESH_INTERVAL_MINUTES` in production — if nobody's looking at
the dashboard, the process is asleep and the timer just doesn't fire.

Rather than pay for an always-on host, the refresh jobs are triggered
externally instead: `POST /api/v1/internal/refresh` (a protected route,
`backend/api/routes/internal.py`) runs the exact same `refresh_all()` the
scheduler calls on its own timer (`backend/core/refresh_jobs.py`), and a
GitHub Actions cron job (`.github/workflows/refresh.yml`, free) calls it
every 30 minutes. The HTTP request itself also wakes the sleeping backend up,
so this solves both problems with one mechanism.

The in-process scheduler is left running too — harmless, since both paths
call the same idempotent `refresh_all()`, and it's what makes local dev via
`scripts/dev.ps1`/`dev.bat` "just work" without needing any of this.

## 1. Database — Neon

1. Create a free project at [neon.tech](https://neon.tech).
2. Copy the connection string it gives you (starts `postgresql://...`).
   Change the driver prefix for asyncpg:
   `postgresql://` → `postgresql+asyncpg://`.
3. Keep this value handy — it's `BACKEND_DATABASE_URL` in step 2.
4. From your machine, apply migrations against Neon once:
   ```powershell
   cd backend
   $env:BACKEND_DATABASE_URL = "postgresql+asyncpg://...<your Neon string>..."
   uv run alembic upgrade head
   ```
   (Neon's free tier autosuspends when idle and wakes automatically on the
   next connection — no manual "unpause" step, unlike some other free
   Postgres hosts.)

## 2. Backend — Render

1. Push this repo to GitHub if you haven't already.
2. In Render: **New > Blueprint**, connect the repo. It finds `render.yaml`
   at the repo root automatically and proposes one web service
   (`weather-fc-backend`, free plan, rooted at `backend/`).
3. Before the first deploy completes, fill in these environment variables in
   the Render dashboard (they're declared with `sync: false` in
   `render.yaml`, meaning Render prompts for them rather than committing
   real values to the repo):

   | Key | Value |
   |---|---|
   | `BACKEND_DATABASE_URL` | the Neon connection string from step 1 |
   | `BACKEND_CORS_ORIGINS` | `["https://<your-vercel-app>.vercel.app"]` — fill in after step 3, then redeploy |
   | `BACKEND_REFRESH_TOKEN` | any long random string you generate — e.g. `openssl rand -hex 32` |
   | `ENTSOE_API_TOKEN` | your real ENTSO-E token |
   | `ESIOS_API_TOKEN` | your real ESIOS token, if you have one |
   | `ELEXON_API_KEY` | optional, leave blank if you don't have one |

4. Note the service's public URL once deployed (`https://weather-fc-backend-XXXX.onrender.com`) — needed in steps 3 and 4.
5. Sanity check: `curl https://<your-render-url>/health` should return `{"status":"ok"}` (or equivalent).

## 3. Frontend — Vercel

1. In Vercel: **New Project**, import the repo, set **Root Directory** to
   `frontend`.
2. Framework preset: Vite (auto-detected). Build command `npm run build`,
   output directory `dist` (defaults are correct).
3. Add one environment variable: `VITE_API_BASE_URL` = the Render URL from
   step 2 (e.g. `https://weather-fc-backend-XXXX.onrender.com`, no trailing
   slash). This is a *build-time* value — Vite bakes it into the JS bundle,
   so changing it later means redeploying.
4. Deploy. Note the resulting `https://<your-app>.vercel.app` URL.
5. Go back to Render and set `BACKEND_CORS_ORIGINS` to
   `["https://<your-app>.vercel.app"]`, then trigger a redeploy — without
   this, the browser will block the frontend's requests to the backend
   (CORS).

## 4. Scheduled refresh — GitHub Actions

1. In the GitHub repo: **Settings > Secrets and variables > Actions**, add:
   - `BACKEND_URL` = the Render URL from step 2 (no trailing slash)
   - `REFRESH_TOKEN` = the exact same value you set for
     `BACKEND_REFRESH_TOKEN` on Render
2. The workflow (`.github/workflows/refresh.yml`) is already committed and
   runs on a `*/30 * * * *` cron automatically — nothing else to do. You can
   trigger it manually from the Actions tab (`workflow_dispatch`) to verify
   it works before waiting for the schedule.
3. Verify: after a manual run, check the Render service logs for
   `price_refresh.done`, `entsoe_generation_refresh.done`, etc., and query
   `/api/v1/prices/day-ahead` on the Render URL to confirm fresh rows are
   landing in Neon.

## Free-tier limitations worth knowing

- **Render free web service**: sleeps after ~15 min idle; first request after
  that takes a few seconds to wake. The GitHub Actions cron doubles as a
  keep-warm ping every 30 minutes, so in practice it rarely stays asleep
  long enough for a dashboard visitor to notice.
- **Neon free tier**: autosuspends compute when idle (wakes automatically,
  no action needed) and caps storage at 0.5 GB — comfortably enough for this
  project's tables for a long time, but worth monitoring if history grows
  for years.
- **GitHub Actions**: cron schedules on *public* repos are free and
  unlimited; on a private repo they draw from the (generous, 2000 min/month)
  free minutes — each refresh run here takes seconds, so 30-minute cadence
  stays well within that either way.
- None of this needs a credit card for Neon, Render, or Vercel's free tiers
  as of this writing — that can and does change, so double-check at signup.
