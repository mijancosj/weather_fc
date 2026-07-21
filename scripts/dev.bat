@echo off
REM Double-click entry point for scripts\dev.ps1 — running a .ps1 by
REM double-clicking it directly hits Windows' default execution policy
REM ("scripts are disabled on this system") and refuses to run at all.
REM This .bat has no such restriction and just hands off to the real
REM logic in dev.ps1 with the policy bypassed for this one process only
REM (does not change any system-wide setting).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0dev.ps1"
pause
