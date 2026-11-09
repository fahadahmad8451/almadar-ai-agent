# Sprint 1 — v0.2: First Live Agent

> **Note (v0.6.0):** the demo company was rebranded to Al Madar Holding with an emerald + gold theme; see [REBRAND.md](REBRAND.md).

Sprint 1 turns the Setup v0.1 skeleton into the first real working
slice: a signed-in user can ask the agent a data question in English
or Arabic and get an answer built from the live database, with the
tools used and the step trace shown. Nothing is mocked — every number
comes from PostgreSQL.

## What is live

### Auth — JWT in httpOnly cookies

- `POST /api/v1/auth/login` — bcrypt password check against the
  seeded users. Access token 15 min + refresh token 24 h, both set as
  httpOnly cookies (`amh_access`, `amh_refresh`). Tokens are never in
  JSON bodies and never in localStorage (same hardened pattern as
  Project 1 v0.10).
- `POST /api/v1/auth/refresh` — rotates the access token from the
  refresh cookie.
- `POST /api/v1/auth/logout` — clears both cookies.
- `GET /api/v1/auth/me` — the signed-in user.
- Wrong password or unknown user → 401 `invalid_credentials`. Demo
  accounts are development-only and refused in production.
- The login body takes a plain string email, not `EmailStr`: the demo
  accounts use the `.local` domain (`manager@almadar.local`), which
  `email-validator` rejects as a reserved special-use domain. A
  regression test pins this.

### RBAC + tool-permission checks

- Three roles: `ADMIN`, `OPERATIONS_MANAGER`, `OPERATIONS_OFFICER`.
- Every tool declares its allowed roles; the registry is the single
  choke point and refuses with 403 before any execution.
- Approvals are the hard rule: only Operations Manager / Admin may
  approve. An Operations Officer gets 403 on
  `POST /api/v1/approvals/{id}/approve` and `/reject`; an unsigned-in
  caller gets 401. Denials are written to the audit log.
- Write tools cannot execute at all in Sprint 1: they need a human
  approval token, which arrives with the Approval Agent in Sprint 2.
  `approve_expense_claim` records a `refused` tool call and raises.

### Tools layer — read-only, real PostgreSQL

| Tool | What it returns |
|---|---|
| `list_invoices(status, period)` | Invoices with supplier, amount, VAT (exactly 15%), totals |
| `list_suppliers(overdue)` | Suppliers; `overdue=true` returns only those with overdue invoices and their overdue totals |
| `list_customers()` | All CRM customers |
| `list_leads(status)` | CRM leads, optionally filtered (e.g. `STALE`) |
| `list_expense_claims(pending)` | Expense claims awaiting a decision (`PENDING` / `FLAGGED`) |
| `get_purchase_order(po_no)` | The invoices recorded against one purchase order |

Every call is parameterised SQLAlchemy — the agent never builds SQL
from user text — and every call is recorded in `tool_calls` with
status, latency, and error. Transient failures retry up to 3 times.

### Data Agent — LangGraph

Graph: Supervisor (intent parse) → Data Agent (choose + call tools)
→ self-check (re-compute totals from the returned rows) → finalize.

- Intent parsing tries the local Ollama LLM first (5 s timeout) and
  falls back to deterministic English + Arabic keyword rules when
  Ollama is unreachable. The agent answers correctly either way.
- Intents in Sprint 1: `pending_invoices`, `overdue_suppliers`,
  `stale_leads`, `pending_expenses`, `customers`, `purchase_order`.
  Anything else is `unknown`: the run is marked `ESCALATED` with
  confidence below 0.70 and no tool is called.
- Confidence below 0.70 escalates to a human; the answer says so
  instead of guessing.

### API

- `POST /api/v1/agent/instruct` `{instruction, language}` → answer +
  rows + tools used + steps trace. Auth required. Rate limit: 10 runs
  per user per hour (429 beyond that).
- `GET /api/v1/agent/runs` and `GET /api/v1/agent/runs/{id}/trace` —
  run history and the per-step trace with tool calls. Operations
  Officers see only their own runs.
- `GET /api/v1/workflows` — the 4 seeded workflows from the database.
- All responses use one envelope:
  `{"success", "data", "error": {"code", "message"}, "request_id"}` —
  including 401/403/404/429 and unmatched routes.

### Frontend

- Login page wired to live auth, with development-only demo account
  buttons that fill the form. Errors are shown honestly.
- New Instruct page (`/instruct`): instruction box, English/Arabic
  selector, example questions, the answer table, tools used,
  confidence, escalation notice, and the steps trace. Sign-out button
  included.
- Landing page unchanged.

## Live verification (2026-11-06)

Against the seeded database, as Operations Manager:

| Instruction | Result |
|---|---|
| "Show me the pending invoices" | 12 invoices, 581,100.19 SAR (VAT 87,165.03 SAR), confidence 1.00 |
| "Who are the overdue suppliers?" | 3 suppliers, 164,941.98 SAR overdue, confidence 1.00 |
| "How many stale leads do we have?" | 4 stale leads, confidence 1.00 |
| "ما هي الفواتير المعلقة؟" (Arabic) | 12 invoices, same totals, Arabic summary, confidence 1.00 |
| "What is the weather today?" | ESCALATED, confidence 0.50, no tools called |

Operations Officer approving → 403 `forbidden`. All three roles log
in successfully. pytest: **46 passed**. Frontend build: passes.

## Still 501 (honest, not faked)

- Report Agent (`POST /api/v1/workflows/{id}/run`,
  `/api/v1/reports`, PDF export) — Sprint 2.
- Approval Agent (`POST /api/v1/approvals/{id}/approve|reject`,
  approval tokens) — Sprint 2.
- Scheduler (`/api/v1/schedules`) — Sprint 3.
- PDF invoice reading / OCR, Admin user management, evals — later
  sprints.
- `POST /api/v1/auth/register` — Admin-only user creation, later
  sprint.

## How to test

```bash
.venv/bin/python -m pytest        # 46 tests, real DB
curl http://127.0.0.1:8100/health # version 0.2.0, database connected
# Sign in as manager@almadar.local / Manager123!, then:
curl -b cookies.txt -X POST http://127.0.0.1:8100/api/v1/agent/instruct \
  -H 'Content-Type: application/json' \
  -d '{"instruction": "Show me the pending invoices"}'
```

## Files changed

- `backend/app/api/v1/auth.py`, `agent.py`, `workflows.py`,
  `approvals.py`, `_helpers.py` — live endpoints.
- `backend/app/core/security.py` — JWT cookies, RBAC helpers, audit.
- `backend/app/tools/erp.py`, `crm.py`, `registry.py` — tools.
- `backend/app/agents/supervisor.py`, `subagents.py` — LangGraph.
- `backend/app/main.py` — envelope error handling (incl. 404s).
- `frontend/src/api/client.ts`, `pages/Login.tsx`,
  `pages/Instruct.tsx` (new), `App.tsx` — live auth + instruct UI.
- `tests/test_auth.py`, `test_tools.py`, `test_agent.py`,
  `test_rbac.py` (new), `test_health.py`, `conftest.py` (new).
