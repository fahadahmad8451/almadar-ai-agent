# PRODUCTION SETUP — Al Madar Holding AI Agent (v0.8.0)
#
# Creates the production PostgreSQL database (almadar_agent_prod),
# generates a fresh JWT secret into .env.production (if missing),
# seeds the database WITHOUT demo accounts, and creates the
# data-prod/ directories. Dev and staging are NOT touched.
#
# After this, create the first Admin:
#   $env:AMH_ENV_FILE = ".env.production"
#   python scripts/create_admin.py --email admin@almadar.local --name "Fahad Ahmad"
# Then start production with .\scripts\production_start.ps1
#
# Usage:  .\scripts\production_setup.ps1
# Needs:  local PostgreSQL on :5432, user postgres (same as dev setup).
$ErrorActionPreference = "Stop"
$Root = (Split-Path -Parent $MyInvocation.MyCommand.Path) | Split-Path -Parent
$env:PGPASSWORD = "${PGPASSWORD:-postgres}"

if (-not (Test-Path "$Root\.env.production")) {
    Write-Host "Creating .env.production from .env.production.example (fresh secret)..."
    Copy-Item "$Root\.env.production.example" "$Root\.env.production"
    $Secret = python -c "import secrets; print(secrets.token_urlsafe(48))"
    (Get-Content "$Root\.env.production") -replace "^JWT_SECRET=.*", "JWT_SECRET=$Secret" |
        Set-Content "$Root\.env.production"
    Write-Host "  Fresh JWT secret generated (32+ chars, never the dev/staging one)."
} else {
    Write-Host ".env.production already exists — keeping its secret."
}

Write-Host "Creating production database almadar_agent_prod (if missing)..."
$exists = psql -h 127.0.0.1 -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = 'almadar_agent_prod'"
if ($exists -ne "1") {
    psql -h 127.0.0.1 -U postgres -d postgres -c "CREATE DATABASE almadar_agent_prod"
}

Write-Host "Seeding production database WITHOUT demo accounts..."
Set-Location $Root
$env:AMH_ENV_FILE = ".env.production"
& "$Root\.venv\Scripts\python.exe" scripts/seed.py --no-demo-users

Write-Host "Creating data-prod directories..."
New-Item -ItemType Directory -Force -Path "$Root\data-prod\exports" | Out-Null
New-Item -ItemType Directory -Force -Path "$Root\data-prod\uploads" | Out-Null
New-Item -ItemType Directory -Force -Path "$Root\data-prod\evals" | Out-Null

Write-Host "Verifying production seed counts..."
psql -h 127.0.0.1 -U postgres -d almadar_agent_prod -c "SELECT (SELECT count(*) FROM users) users, (SELECT count(*) FROM erp_suppliers) suppliers, (SELECT count(*) FROM erp_invoices) invoices, (SELECT count(*) FROM erp_invoices WHERE status='PENDING') pending, (SELECT count(*) FROM crm_customers) customers, (SELECT count(*) FROM crm_leads) leads, (SELECT count(*) FROM crm_deals) deals, (SELECT count(*) FROM expense_claims) claims, (SELECT count(*) FROM workflows) workflows, (SELECT count(*) FROM scheduled_jobs) scheduled_jobs;"

Write-Host "Production setup done. Next:"
Write-Host "  1. Create the first Admin (see header above)"
Write-Host "  2. .\scripts\production_start.ps1   (stops dev servers first — prod uses ports 8100/3100)"
