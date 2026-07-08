# Runs the backend API and the frontend dev server side by side.
# Ctrl+C stops this script; the child processes are stopped with it.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

$backend = Start-Process -PassThru -NoNewWindow `
    -WorkingDirectory (Join-Path $root "backend") `
    -FilePath "uv" -ArgumentList "run", "fastapi", "dev", "src/backend/main.py", "--port", "8000"

$frontend = Start-Process -PassThru -NoNewWindow `
    -WorkingDirectory (Join-Path $root "frontend") `
    -FilePath "npm" -ArgumentList "run", "dev"

Write-Host "backend  -> http://localhost:8000  (pid $($backend.Id))"
Write-Host "frontend -> http://localhost:5173  (pid $($frontend.Id))"
Write-Host "Ctrl+C to stop both."

try {
    Wait-Process -Id $backend.Id, $frontend.Id
} finally {
    Stop-Process -Id $backend.Id, $frontend.Id -ErrorAction SilentlyContinue
}
