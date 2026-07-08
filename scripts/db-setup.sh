#!/usr/bin/env bash
# Creates the app-scoped Postgres role + database used by backend/.env.example's
# default BACKEND_DATABASE_URL. Run once, after PostgreSQL itself is installed
# and running (see docs/postgres-setup.md). Safe to re-run — skips what already exists.
set -euo pipefail

pg_superuser="postgres"
pg_superuser_password="postgres"
app_role="price_discovery"
app_password="price_discovery"
app_database="price_discovery"

export PGPASSWORD="${pg_superuser_password}"

role_exists=$(psql -U "${pg_superuser}" -h localhost -tAc "SELECT 1 FROM pg_roles WHERE rolname='${app_role}'")
if [ "${role_exists}" != "1" ]; then
    echo "==> creating role ${app_role}"
    psql -U "${pg_superuser}" -h localhost -c "CREATE ROLE ${app_role} WITH LOGIN PASSWORD '${app_password}';"
else
    echo "==> role ${app_role} already exists"
fi

db_exists=$(psql -U "${pg_superuser}" -h localhost -tAc "SELECT 1 FROM pg_database WHERE datname='${app_database}'")
if [ "${db_exists}" != "1" ]; then
    echo "==> creating database ${app_database} (owner: ${app_role})"
    psql -U "${pg_superuser}" -h localhost -c "CREATE DATABASE ${app_database} OWNER ${app_role};"
else
    echo "==> database ${app_database} already exists"
fi

unset PGPASSWORD

echo
echo "Done. Next: cd backend && uv run alembic upgrade head"
