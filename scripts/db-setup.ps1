# Creates the app-scoped Postgres role + database used by backend/.env.example's
# default BACKEND_DATABASE_URL. Run once, after PostgreSQL itself is installed
# and running (see docs/postgres-setup.md). Safe to re-run — skips what already exists.

$ErrorActionPreference = "Stop"

$PgSuperuser = "postgres"
$PgSuperuserPassword = "postgres"
$AppRole = "price_discovery"
$AppPassword = "price_discovery"
$AppDatabase = "price_discovery"

$env:PGPASSWORD = $PgSuperuserPassword

$roleExists = (psql -U $PgSuperuser -h localhost -tAc "SELECT 1 FROM pg_roles WHERE rolname='$AppRole'")
if ($roleExists -ne "1") {
    Write-Host "==> creating role $AppRole"
    psql -U $PgSuperuser -h localhost -c "CREATE ROLE $AppRole WITH LOGIN PASSWORD '$AppPassword';"
} else {
    Write-Host "==> role $AppRole already exists"
}

$dbExists = (psql -U $PgSuperuser -h localhost -tAc "SELECT 1 FROM pg_database WHERE datname='$AppDatabase'")
if ($dbExists -ne "1") {
    Write-Host "==> creating database $AppDatabase (owner: $AppRole)"
    psql -U $PgSuperuser -h localhost -c "CREATE DATABASE $AppDatabase OWNER $AppRole;"
} else {
    Write-Host "==> database $AppDatabase already exists"
}

Remove-Item Env:\PGPASSWORD

Write-Host ""
Write-Host "Done. Next: cd backend; uv run alembic upgrade head"
