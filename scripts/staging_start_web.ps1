# STAGING START WEB — Al Madar Holding AI Agent (v0.5)
#
# Serves the staging frontend build on :3101. The build is the same
# artifact as dev (relative /api paths); only the Vite proxy target
# differs (AMH_API_TARGET -> staging API :8101), so the browser still
# talks to one origin and the httpOnly cookies stay first-party.
# Requires the staging build: .\scripts\staging_build_web.ps1
# (or: npm run build:staging in frontend\).
# Foreground — Ctrl+C stops it. Dev preview (:3100) is NOT touched.
#
# Usage:  .\scripts\staging_start_web.ps1
$ErrorActionPreference = "Stop"
$Root = (Split-Path -Parent $MyInvocation.MyCommand.Path) | Split-Path -Parent

if (-not (Test-Path "$Root\frontend\dist-staging")) {
    Write-Host "ERROR: frontend\dist-staging not found — run .\scripts\staging_build_web.ps1 first."
    exit 1
}

Write-Host "Staging web starting on http://127.0.0.1:3101 (API proxy -> :8101)"
Write-Host "  (dev preview on :3100 is untouched — both can run side by side)"
Set-Location "$Root\frontend"
$env:AMH_API_TARGET = "http://127.0.0.1:8101"
npm run preview:staging
