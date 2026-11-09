# PRODUCTION START — Al Madar Holding AI Agent (v0.8.0)
#
# Starts the production API on :8100 with production env loaded from
# .env.production (AMH_ENV_FILE). Foreground — Ctrl+C stops it.
#
# Production REUSES the dev ports (API 8100 / Web 3100), so the dev
# servers are stopped first (same rule as Project 1). Dev data is
# untouched — only the ports are freed. Restart dev afterwards with
# .\scripts\dev_start.ps1 (+ dev_start_web.ps1).
#
# Scheduler is ON in production (the three locked jobs fire on their
# schedule, running as the Admin created by create_admin.py).
# --no-server-header hides the Server header (hardening, v0.8.0).
#
# Usage:  .\scripts\production_start.ps1
$ErrorActionPreference = "Stop"
$Root = (Split-Path -Parent $MyInvocation.MyCommand.Path) | Split-Path -Parent

if (-not (Test-Path "$Root\.env.production")) {
    Write-Host "ERROR: $Root\.env.production not found — run .\scripts\production_setup.ps1 first."
    exit 1
}
if (-not (Test-Path "$Root\.venv")) {
    Write-Host "ERROR: venv not found at $Root\.venv — run .\scripts\dev_start.ps1 once first."
    exit 1
}

Write-Host "Stopping dev servers (production reuses ports 8100/3100)..."
Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -match "uvicorn app.main:app --port 8100" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Get-CimInstance Win32_Process -Filter "Name = 'node.exe'" |
    Where-Object { $_.CommandLine -match "vite preview --port 3100" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep -Seconds 1

Write-Host "Production API starting on http://127.0.0.1:8100"
Write-Host "  AMH_ENV_FILE=.env.production  ENVIRONMENT=production  DATABASE=almadar_agent_prod"
Write-Host "  Demo accounts: OFF · Scheduler: ON · CORS: localhost:3100 only"
Set-Location $Root
$env:AMH_ENV_FILE = ".env.production"
& "$Root\.venv\Scripts\uvicorn.exe" app.main:app --port 8100 --host 127.0.0.1 --app-dir backend --no-server-header
