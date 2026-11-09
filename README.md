# Al Madar Holding — Enterprise AI Agent

An AI operations assistant for a fictional Saudi business group
(trading, logistics, contracting). Staff instruct the agent in plain
English or Arabic; the agent gathers data from simulated ERP and CRM
systems, drafts the work, checks its own output, and nothing
irreversible executes without a human manager's approval.

This is **Project 2** of a Saudi enterprise AI portfolio (Project 1:
Enterprise Intelligence Platform — RAG with citations, RBAC, audit
trail). A different fictional organisation from Project 1: this one runs a
business group's operations — doing the work, not just answering
questions.

## What it does

Four core workflows:

| Workflow | What happens |
|---|---|
| Pending Invoices Report | ERP invoice data → pending filter → overdue suppliers → manager approval → export |
| Overdue Supplier Follow-up | Reminder email drafts for overdue suppliers — saved only after approval |
| CRM Follow-up | Prioritised follow-up list for stale leads and inactive customers |
| Expense Approval | Pending expense claims with policy flags, approved per claim |

Advanced capabilities (locked in the plan): agent long-term memory,
self-check / reflection loop, scheduled workflows, confidence scoring
with escalation, full observability with evals, PDF invoice reading
(OCR → PO match), and parallel multi-agent execution.

## Architecture

```
React 18 + TypeScript + Tailwind  →  FastAPI + LangGraph  →  PostgreSQL 16
(frontend :3100)                    (supervisor + sub-agents)  (ERP/CRM data,
                                    tools, approvals, audit)    memory, jobs)
                                    Ollama (local LLM, with keyword fallback)
```

- **Human approval first.** The agent proposes; a human disposes. No
  payment, supplier approval, or irreversible transaction ever executes
  without approval — enforced in the tool layer, not just the UI.
- **Permission-aware tools.** Every tool declares the roles allowed to
  call it.
- **Audit everything.** Every instruction, tool call, approval, and
  execution is logged.
- **Synthetic data only.** No real customer, supplier, or financial
  data. No real ERP/CRM, no real email sending, no real payments.

## Status — v0.9.0 (Monitoring)

v0.9.0 completes the process with **monitoring**: every request is
recorded in PostgreSQL (`request_metrics`), six locked alert rules
(instruct p95 > 500 ms, 5xx rate > 5%, eval fail, pending approvals
> 50, missed scheduler fire, API/DB down) checked every 5 minutes
in production, an Admin-only Monitoring page (`/monitoring`), a
daily report script, and rotating file logs (5 MB, 5 backups). See
[docs/MONITORING.md](docs/MONITORING.md).

v0.8.0 takes the system to **local production**: a separate production
database (`almadar_agent_prod`), demo accounts OFF (first Admin via
`scripts/create_admin.py`), security headers, a login rate limit
(5 failed/min → 429), backup/restore scripts (live-tested), and a
dedicated read-only `GET /api/v1/dashboard/summary` endpoint — the
Dashboard home now reads every KPI straight from the database instead
of spending the shared instruct budget. Production runs on the dev
ports (API 8100 / web 3100) with the dev servers stopped. See
[docs/PRODUCTION.md](docs/PRODUCTION.md) for the full runbook and
rollback plan.

Sprint 3 completes the operations loop. The scheduler runs the three
locked jobs (daily invoice check 08:00, weekly CRM digest Monday
09:00, month-end supplier summary 1st 09:00, Asia/Riyadh) as normal
workflow runs — a scheduled run builds the report and queues it for
approval, exactly like a manual run. Supplier invoice PDFs can be
uploaded: fields are extracted, matched against the purchase order
(including the 15% VAT rule), and a mismatch is queued as DISPUTED
for a manager to review. Admins manage users, roles, and password
resets and read the audit log and observability metrics. Twelve
scripted eval scenarios run on demand and score the system against
the design targets. Nothing executes without a human approval.

| Check | Result |
|---|---|
| Backend `/health` (incl. database: connected) | Live |
| Login / refresh / logout (3 roles) | Live |
| `POST /api/v1/agent/instruct` (EN + AR) | Live |
| `GET /api/v1/workflows` (4 seeded workflows) | Live |
| `POST /api/v1/workflows/{key}/run` (4 workflows, AWAITING_APPROVAL) | Live |
| Approvals queue + approve / reject (token-enforced) | Live |
| Report exports PDF / CSV / XLSX (real files) | Live |
| Frontend: Instruct / Workflows / Approvals / Reports | Live |
| Scheduler + run-now + n8n webhook | Live |
| PDF invoice upload (PO match / mismatch) | Live |
| Admin (users, roles, reset, audit, observability) | Live |
| Evals (12 scenarios) | 12/12 PASS |
| pytest | 105 passed |
| Staging smoke (API :8101 / Web :3101) | 31/31 PASS |
| Frontend build | Passes |
| PostgreSQL seed | Realistic synthetic data |

Details: [docs/SPRINT3.md](docs/SPRINT3.md), [docs/TESTING.md](docs/TESTING.md),
[docs/STAGING.md](docs/STAGING.md).

## Quick start

```bash
# 1. Database (local PostgreSQL 16, database almadar_agent)
sudo -u postgres psql -c "CREATE DATABASE almadar_agent;"
python scripts/seed.py

# 2. Backend (API :8100)
python -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
.venv/bin/uvicorn app.main:app --port 8100 --app-dir backend
# or: bash scripts/dev_start.sh

# 3. Frontend (web :3100)
cd frontend && npm install && npm run dev

# 4. Verify
python scripts/healthcheck.py
python -m pytest
```

Full instructions: [docs/SETUP.md](docs/SETUP.md).
Design: `../Project-2-Design.md` (in the portfolio files).
Requirements: `../Project-2-AI-Agent-Plan.md`.

## Tech

Python 3.12, FastAPI, SQLAlchemy, LangGraph, PostgreSQL 16 + pgvector,
React 18, TypeScript, Vite, Tailwind CSS, Ollama (Llama 3.1 8B +
Qwen2.5 7B), PaddleOCR, APScheduler. Cost $0 — local models, local
database, no cloud. No Docker (the target laptop cannot run it).

## Roadmap

Requirements → Estimate → **Design** → **Setup (v0.1)** →
**Sprint 1 (v0.2)** → **Sprint 2 (v0.3)** → **Sprint 3 (v0.4)**
→ **Testing (GO)** → **Staging (v0.5)** → **Rebrand (v0.6)** →
**Structure rebuild (v0.7, this release)**
→ Production → Monitoring.
