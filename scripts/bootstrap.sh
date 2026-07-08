#!/usr/bin/env bash
# Bootstraps every independent sub-project in this repo: one uv-managed venv
# per Python package, plus npm install for the frontend. Safe to re-run.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python_projects=(
    "data-services/entsoe-retriever"
    "data-services/elexon-retriever"
    "backend"
)

for project in "${python_projects[@]}"; do
    echo "==> uv sync in ${project}"
    (cd "${root}/${project}" && uv sync --extra dev)
done

echo "==> npm install in frontend"
(cd "${root}/frontend" && npm install)

echo
echo "Done. Remaining one-time steps:"
echo "  1. Copy each .env.example to .env and fill in secrets."
echo "  2. Set up Postgres if you haven't: see docs/postgres-setup.md, then ./scripts/db-setup.sh"
echo "  3. cd backend && uv run alembic upgrade head"
echo "  4. ./scripts/dev.sh"
