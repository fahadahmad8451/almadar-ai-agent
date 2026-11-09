# Setup — Project 2: Enterprise AI Agent (v0.2)

Local-first setup. No Docker. Ports: API **8100**, web **3100**
(Project 1 uses 8000/3000 — no conflict).

## Prerequisites

- Python 3.12
- Node.js 20+ and npm
- PostgreSQL 16 running locally (see below)
- Ollama: optional in v0.2. The Supervisor tries the local LLM first
  (5 s timeout) and falls back to deterministic keyword rules when
  Ollama is unreachable — the agent still answers correctly.

## 1. Database — real PostgreSQL

The database is real: 18 tables (Design section 4, plus
`expense_claims`, which the design's table list omitted but the
expense workflow needs) and realistic seeded data.

```bash
# Start PostgreSQL if it is down
sudo pg_ctlcluster 16 main start

# Create the database (once)
sudo -u postgres psql -c "CREATE DATABASE almadar_agent;"

# Create the tables (also done automatically at app startup)
# and load the seed data (Saudi suppliers, invoices with 15% VAT,
# CRM customers/leads/deals, expense claims, demo users, workflows,
# scheduled jobs). Idempotent — safe to re-run.
python scripts/seed.py
```

Seed output lists the row count per table (users: 3, suppliers: 10,
invoices: 24, customers: 8, leads: 10, deals: 6, expense_claims: 10,
workflows: 4, scheduled_jobs: 3).

Demo accounts (DEMO ONLY — disabled in production, same rule as
Project 1): `admin@almadar.local` / `Admin123!` (Admin),
`manager@almadar.local` / `Manager123!` (Operations Manager),
`ops@almadar.local` / `Ops123!` (Operations Officer).

If PostgreSQL is unreachable, the app still starts but `/health`
honestly reports `"database": "unavailable: ..."`. There is no
in-memory or SQLite fallback.

## 2. Backend

```bash
python -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/uvicorn app.main:app --port 8100 --app-dir backend
# or: bash scripts/dev_start.sh        (Linux/macOS)
# or: powershell scripts/dev_start.ps1 (Windows)
```

Check: `curl http://127.0.0.1:8100/health` — expect
`{"status": "ok", "version": "0.2.0", "service": "almadar-ai-agent",
"database": "connected", ...}`.

## 3. Frontend

```bash
cd frontend
npm install
npm run dev     # http://localhost:3100
# production build: npm run build
```

The landing page shows the four workflows and the live API status.
Sign-in is live in v0.2 (JWT in httpOnly cookies); after signing in,
the Instruct page (`/instruct`) answers data questions in English and
Arabic.

## 4. Tests

```bash
python scripts/seed.py   # tests assume the database is seeded
.venv/bin/python -m pytest
```

`tests/test_health.py` — health live + remaining 501s.
`tests/test_db.py` — all tables exist and seed counts match.
`tests/test_auth.py` — login / refresh / logout / me, all three
roles. `tests/test_tools.py` — real-DB tool results, counts, filters,
VAT, and the tool_calls record. `tests/test_agent.py` — the three
scripted instructions (EN + AR), escalation, and the step trace.
`tests/test_rbac.py` — Operations Officer gets 403 on approve.
Tests need local PostgreSQL running (CI provides a postgres service).

## 5. Verify everything

```bash
python scripts/healthcheck.py   # exit 0 only if API + database are up
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `database: unavailable: connection refused` | Start PostgreSQL: `sudo pg_ctlcluster 16 main start` |
| `database "almadar_agent" does not exist` | Create it (step 1) and re-run `python scripts/seed.py` |
| `password authentication failed for user "postgres"` | Set it: `sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'postgres';"` |
| Frontend shows "API offline" | Start the backend (step 2) — the page calls `/api/v1/health` |
| Port 8100/3100 already in use | Something else is listening; stop it or change `API_PORT`/`WEB_PORT` in `.env` |
