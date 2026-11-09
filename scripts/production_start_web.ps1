# PRODUCTION START WEB — Al Madar Holding AI Agent (v0.8.0)
#
# Serves the production frontend build on :3100 (vite preview).
# Rebuild first after any frontend change:
#   cd frontend; npm run build
# The production API must be running on :8100 first.
#
# Usage:  .\scripts\production_start_web.ps1
$ErrorActionPreference = "Stop"
$Root = (Split-Path -Parent $MyInvocation.MyCommand.Path) | Split-Path -Parent

if (-not (Test-Path "$Root\frontend\dist")) {
    Write-Host "ERROR: frontend\dist not found — run 'cd frontend; npm run build' first."
    exit 1
}

Write-Host "Stopping dev web preview (production reuses port 3100)..."
Get-CimInstance Win32_Process -Filter "Name = 'node.exe'" |
    Where-Object { $_.CommandLine -match "vite preview --port 3100" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep -Seconds 1

Write-Host "Production web starting on http://127.0.0.1:3100"
Set-Location "$Root\frontend"
npx vite preview --port 3100 --host 127.0.0.1
