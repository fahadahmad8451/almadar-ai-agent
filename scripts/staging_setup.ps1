# STAGING SETUP — Al Madar Holding AI Agent (v0.5)
#
# Creates the staging PostgreSQL database (almadar_agent_staging) and seeds
# it with the same synthetic data as dev. Dev (almadar_agent) is NOT touched.
# The scheduler stays OFF in staging; jobs are manual-only.
#
# Usage:  .\scripts\staging_setup.ps1
# Needs:  local PostgreSQL on :5432, user postgres (same as dev setup).
$ErrorActionPreference = "Stop"
$Root = (Split-Path -Parent $MyInvocation.MyCommand.Path) | Split-Path -Parent
$env:PGPASSWORD = if ($env:PGPASSWORD) { $env:PGPASSWORD } else { "postgres" }

if (-not (Test-Path "$Root\.env.staging")) {
    Write-Host "ERROR: $Root\.env.staging not found."
    exit 1
}

Write-Host "Creating staging database almadar_agent_staging (if missing)..."
$exists = psql -h 127.0.0.1 -U postgres -d postgres -t -c "SELECT 1 FROM pg_database WHERE datname = 'almadar_agent_staging'"
if ($exists -notmatch "1") {
    psql -h 127.0.0.1 -U postgres -d postgres -c "CREATE DATABASE almadar_agent_staging"
}

Write-Host "Seeding staging database (AMH_ENV_FILE=.env.staging)..."
Set-Location $Root
$env:AMH_ENV_FILE = ".env.staging"
& "$Root\.venv\Scripts\python.exe" scripts\seed.py

Write-Host "Verifying staging seed counts..."
psql -h 127.0.0.1 -U postgres -d almadar_agent_staging -c "SELECT (SELECT count(*) FROM users) users, (SELECT count(*) FROM erp_suppliers) suppliers, (SELECT count(*) FROM erp_invoices) invoices, (SELECT count(*) FROM erp_invoices WHERE status='PENDING') pending, (SELECT count(*) FROM crm_customers) customers, (SELECT count(*) FROM crm_leads) leads, (SELECT count(*) FROM crm_deals) deals, (SELECT count(*) FROM expense_claims) claims, (SELECT count(*) FROM workflows) workflows, (SELECT count(*) FROM scheduled_jobs) scheduled_jobs;"

Write-Host "Staging setup done. Start it with .\scripts\staging_start.ps1"
