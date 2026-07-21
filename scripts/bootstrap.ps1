# Bootstraps every independent sub-project in this repo: one uv-managed venv
# per Python package, plus npm install for the frontend. Safe to re-run.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

$pythonProjects = @(
    "data-services/entsoe-retriever",
    "data-services/elexon-retriever",
    "backend"
)

foreach ($project in $pythonProjects) {
    $path = Join-Path $root $project
    Write-Host "==> uv sync in $project"
    Push-Location $path
    uv sync --extra dev
    Pop-Location
}

Write-Host "==> npm install in frontend"
Push-Location (Join-Path $root "frontend")
npm install
Pop-Location

Write-Host ""
Write-Host "Done. Remaining one-time steps:"
Write-Host "  1. Fill in the .env in each package (already checked in with dummy placeholders)."
Write-Host "  2. Set up Postgres if you haven't: see docs/postgres-setup.md, then .\scripts\db-setup.ps1"
Write-Host "  3. cd backend; uv run alembic upgrade head"
Write-Host "  4. .\scripts\dev.ps1"
