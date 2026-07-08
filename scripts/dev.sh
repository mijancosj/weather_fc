#!/usr/bin/env bash
# Runs the backend API and the frontend dev server side by side.
# Ctrl+C stops both.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

(cd "${root}/backend" && uv run uvicorn backend.main:app --app-dir src --reload --port 8000) &
backend_pid=$!

(cd "${root}/frontend" && npm run dev) &
frontend_pid=$!

echo "backend  -> http://localhost:8000  (pid ${backend_pid})"
echo "frontend -> http://localhost:5173  (pid ${frontend_pid})"

trap 'kill "${backend_pid}" "${frontend_pid}" 2>/dev/null' EXIT
wait
