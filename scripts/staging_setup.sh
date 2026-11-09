#!/usr/bin/env bash
# STAGING SETUP — Al Madar Holding AI Agent (v0.5)
#
# Creates the staging PostgreSQL database (almadar_agent_staging) and seeds
# it with the same synthetic data as dev. Dev (almadar_agent) is NOT touched.
# The scheduler stays OFF in staging; jobs are manual-only.
#
# Usage:  ./scripts/staging_setup.sh
# Needs:  local PostgreSQL on :5432, user postgres (same as dev setup).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PGPASSWORD="${PGPASSWORD:-postgres}"

if [ ! -f "$ROOT/.env.staging" ]; then
    echo "ERROR: $ROOT/.env.staging not found."
    exit 1
fi

echo "Creating staging database almadar_agent_staging (if missing)..."
psql -h 127.0.0.1 -U postgres -d postgres -tc \
    "SELECT 1 FROM pg_database WHERE datname = 'almadar_agent_staging'" \
    | grep -q 1 || psql -h 127.0.0.1 -U postgres -d postgres \
    -c "CREATE DATABASE almadar_agent_staging"

echo "Seeding staging database (AMH_ENV_FILE=.env.staging)..."
cd "$ROOT"
AMH_ENV_FILE=.env.staging "$ROOT/.venv/bin/python" scripts/seed.py

echo "Verifying staging seed counts..."
psql -h 127.0.0.1 -U postgres -d almadar_agent_staging -c \
    "SELECT (SELECT count(*) FROM users) users,
            (SELECT count(*) FROM erp_suppliers) suppliers,
            (SELECT count(*) FROM erp_invoices) invoices,
            (SELECT count(*) FROM erp_invoices WHERE status='PENDING') pending,
            (SELECT count(*) FROM crm_customers) customers,
            (SELECT count(*) FROM crm_leads) leads,
            (SELECT count(*) FROM crm_deals) deals,
            (SELECT count(*) FROM expense_claims) claims,
            (SELECT count(*) FROM workflows) workflows,
            (SELECT count(*) FROM scheduled_jobs) scheduled_jobs;"

echo "Staging setup done. Start it with ./scripts/staging_start.sh"
