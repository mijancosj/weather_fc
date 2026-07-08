# Runs the backend API and the frontend dev server side by side.
# Ctrl+C stops this script; the child processes are stopped with it.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

function Resolve-Uv {
    $cmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    # uv was just installed (e.g. via winget) and this shell predates the PATH
    # update — fall back to finding it directly instead of failing.
    $wingetUv = Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages") `
        -Filter "uv.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($wingetUv) { return $wingetUv.FullName }

    throw "Could not find 'uv' on PATH. Install it (https://docs.astral.sh/uv/) then open a new terminal."
}

$uvPath = Resolve-Uv

# Plain uvicorn, not `fastapi dev` — the latter's startup banner prints an
# emoji via `rich`, and on a real Windows console (not a redirected/piped
# one) rich's legacy-console writer queries the OS console codepage directly
# (GetConsoleOutputCP), which ignores Python's own UTF-8 I/O settings and
# crashes with UnicodeEncodeError on the default cp1252 codepage. Plain
# uvicorn's logging never touches that code path.
$backend = Start-Process -PassThru -NoNewWindow `
    -WorkingDirectory (Join-Path $root "backend") `
    -FilePath $uvPath -ArgumentList "run", "uvicorn", "backend.main:app", "--app-dir", "src", "--reload", "--port", "8000"

# npm on Windows is npm.cmd, not a real .exe — Start-Process -NoNewWindow uses
# raw CreateProcess, which can't launch .cmd files directly, so it has to be
# run through cmd.exe instead of being passed as -FilePath itself.
$frontend = Start-Process -PassThru -NoNewWindow `
    -WorkingDirectory (Join-Path $root "frontend") `
    -FilePath "cmd.exe" -ArgumentList "/c", "npm run dev"

Write-Host "backend  -> http://localhost:8000  (pid $($backend.Id))"
Write-Host "frontend -> http://localhost:5173  (pid $($frontend.Id))"
Write-Host "Ctrl+C to stop both."

try {
    Wait-Process -Id $backend.Id, $frontend.Id
} finally {
    Stop-Process -Id $backend.Id, $frontend.Id -ErrorAction SilentlyContinue
}
