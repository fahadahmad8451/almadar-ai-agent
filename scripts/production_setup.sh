#!/usr/bin/env bash
# PRODUCTION SETUP — Al Madar Holding AI Agent (v0.8.0)
#
# Creates the production PostgreSQL database (almadar_agent_prod),
# generates a fresh JWT secret into .env.production (if missing),
# seeds the database WITHOUT demo accounts, and creates the
# data-prod/ directories. Dev (almadar_agent) and staging
# (almadar_agent_staging) are NOT touched.
#
# After this, create the first Admin:
#   AMH_ENV_FILE=.env.production python scripts/create_admin.py \
#       --email admin@almadar.local --name "Fahad Ahmad"
# Then start production with ./scripts/production_start.sh
#
# Usage:  ./scripts/production_setup.sh
# Needs:  local PostgreSQL on :5432, user postgres (same as dev setup).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PGPASSWORD="${PGPASSWORD:-postgres}"

if [ ! -f "$ROOT/.env.production" ]; then
    echo "Creating .env.production from .env.production.example (fresh secret)..."
    cp "$ROOT/.env.production.example" "$ROOT/.env.production"
    SECRET="$("$ROOT/.venv/bin/python" -c "import secrets; print(secrets.token_urlsafe(48))" 2>/dev/null || python3 -c "import secrets; print(secrets.token_urlsafe(48))")"
    # Replace the placeholder secret line (macOS/Linux-safe).
    if sed --version >/dev/null 2>&1; then
        sed -i "s|^JWT_SECRET=.*|JWT_SECRET=$SECRET|" "$ROOT/.env.production"
    else
        sed -i '' "s|^JWT_SECRET=.*|JWT_SECRET=$SECRET|" "$ROOT/.env.production"
    fi
    echo "  Fresh JWT secret generated (32+ chars, never the dev/staging one)."
else
    echo ".env.production already exists — keeping its secret."
fi

echo "Creating production database almadar_agent_prod (if missing)..."
psql -h 127.0.0.1 -U postgres -d postgres -tc \
    "SELECT 1 FROM pg_database WHERE datname = 'almadar_agent_prod'" \
    | grep -q 1 || psql -h 127.0.0.1 -U postgres -d postgres \
    -c "CREATE DATABASE almadar_agent_prod"

echo "Seeding production database WITHOUT demo accounts..."
cd "$ROOT"
AMH_ENV_FILE=.env.production "$ROOT/.venv/bin/python" scripts/seed.py --no-demo-users

echo "Creating data-prod directories..."
mkdir -p "$ROOT/data-prod/exports" "$ROOT/data-prod/uploads" "$ROOT/data-prod/evals"

echo "Verifying production seed counts..."
psql -h 127.0.0.1 -U postgres -d almadar_agent_prod -c \
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

echo "Production setup done. Next:"
echo "  1. AMH_ENV_FILE=.env.production python scripts/create_admin.py --email <you> --name \"<name>\""
echo "  2. ./scripts/production_start.sh   (stops dev servers first — prod uses ports 8100/3100)"
