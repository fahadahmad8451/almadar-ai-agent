# STAGING BUILD WEB — Al Madar Holding AI Agent (v0.5)
#
# Builds the staging frontend into frontend/dist-staging (dev's
# frontend/dist is NOT touched). The build is environment-agnostic
# (relative /api paths); the API target is set at preview time by
# AMH_API_TARGET in scripts/staging_start_web.ps1.
#
# Usage:  .\scripts\staging_build_web.ps1
$ErrorActionPreference = "Stop"
$Root = (Split-Path -Parent $MyInvocation.MyCommand.Path) | Split-Path -Parent
Set-Location "$Root\frontend"
if (-not (Test-Path node_modules)) {
    npm install
}
npm run build:staging
Write-Host "Staging web build done: frontend\dist-staging"
