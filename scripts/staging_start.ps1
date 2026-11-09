# STAGING START — Al Madar Holding AI Agent (v0.5)
#
# Starts the staging API on :8101 with staging env loaded from
# .env.staging (AMH_ENV_FILE). Foreground — Ctrl+C stops it.
# Dev (port 8100) is NOT touched and can run at the same time.
# Scheduler is OFF in staging (SCHEDULER_ENABLED=false).
#
# Usage:  .\scripts\staging_start.ps1
$ErrorActionPreference = "Stop"
$Root = (Split-Path -Parent $MyInvocation.MyCommand.Path) | Split-Path -Parent

if (-not (Test-Path "$Root\.env.staging")) {
    Write-Host "ERROR: $Root\.env.staging not found — run .\scripts\staging_setup.ps1 first."
    exit 1
}
if (-not (Test-Path "$Root\.venv")) {
    Write-Host "ERROR: venv not found at $Root\.venv — run .\scripts\dev_start.ps1 once first."
    exit 1
}

Write-Host "Staging API starting on http://127.0.0.1:8101"
Write-Host "  AMH_ENV_FILE=.env.staging  ENVIRONMENT=staging  DATABASE=almadar_agent_staging"
Write-Host "  Scheduler: OFF (manual runs only)"
Write-Host "  (dev on :8100 is untouched — both can run side by side)"
Set-Location $Root
$env:AMH_ENV_FILE = ".env.staging"
& "$Root\.venv\Scripts\uvicorn.exe" app.main:app --port 8101 --host 127.0.0.1 --app-dir backend
