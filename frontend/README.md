# frontend

React + Vite + TypeScript dashboard for the price discovery platform.
Completely independent of the Python side — it only knows about
`backend`'s HTTP API (`src/api/client.ts`), proxied at `/api` in dev
(`vite.config.ts`) to `http://localhost:8000`.

## Setup

```powershell
npm install
```

## Run

```powershell
npm run dev
```

Opens on http://localhost:5173. Requires `backend` running on port 8000 (see
`../backend/README.md`) for data to load.

## Structure

```
src/
├── api/          # typed fetch wrappers around the backend REST API
├── components/   # shared, presentational components
├── features/     # feature folders (dashboard, ...), each owns its own UI + queries
├── pages/        # route-level components (add as routes grow)
└── styles/       # Tailwind entrypoint
```

## Tests / lint

```powershell
npm run test
npm run lint
```
