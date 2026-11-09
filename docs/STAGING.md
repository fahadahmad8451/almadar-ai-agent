# Staging — Project 2 (Enterprise AI Agent) v0.5

> **Note (v0.6.0):** the demo company was rebranded to Al Madar Holding with an emerald + gold theme; see [REBRAND.md](REBRAND.md).

Date: 2026-11-06. Version: **0.5.0**. Testing gate: **GO for Staging**
(53/53 journeys, `docs/TESTING.md`). Staging is a separate environment
from dev — its own database, ports, data dirs, JWT secret and frontend
build — so staging can be exercised and broken without touching dev.

## 1. Environment

| Item | Dev | Staging |
|---|---|---|
| PostgreSQL database | `almadar_agent` | `almadar_agent_staging` |
| API | http://127.0.0.1:8100 | http://127.0.0.1:8101 |
| Web (preview) | http://127.0.0.1:3100 | http://127.0.0.1:3101 |
| Env file | `.env` (or built-in defaults) | `.env.staging` (`AMH_ENV_FILE=.env.staging`) |
| JWT secret | dev default | fresh 64-hex secret in `.env.staging` (never committed) |
| Export / upload dirs | `data/exports`, `data/uploads` | `data-staging/exports`, `data-staging/uploads` |
| CORS origins | :3100 only | :3101 only |
| Scheduler (APScheduler) | ON | **OFF** — jobs visible, manual-only |
| Demo accounts | ON | ON (staging is for testing) |
| n8n webhook | disabled (no secret) | disabled (no secret) |
| Frontend build | `frontend/dist` | `frontend/dist-staging` |

The backend loads its env file from `AMH_ENV_FILE` (default `.env`);
see `backend/app/core/config.py`. The frontend build is
environment-agnostic (relative `/api` paths); only the Vite proxy
target differs, set at preview time by `AMH_API_TARGET`
(`frontend/vite.config.ts`). The browser therefore still talks to one
origin and the httpOnly cookies stay first-party — the same pattern
that fixed the Sprint 1 login bounce.

## 2. Setup, start, stop

```bash
# One time (creates + seeds almadar_agent_staging; dev untouched)
./scripts/staging_setup.sh        # Windows: .\scripts\staging_setup.ps1

# Frontend staging build (dev's dist is not touched)
./scripts/staging_build_web.sh    # Windows: .\scripts\staging_build_web.ps1

# Start (each foreground; run in separate terminals)
./scripts/staging_start.sh        # API :8101 — Windows: staging_start.ps1
./scripts/staging_start_web.sh    # Web :3101 — Windows: staging_start_web.ps1

# Stop both
./scripts/staging_stop.sh         # Windows: .\scripts\staging_stop.ps1
```

Seed verification (staging, after setup): 3 users, 10 suppliers,
24 invoices (12 PENDING, 6 PAID, 4 OVERDUE, 2 DISPUTED), 8 customers,
10 leads, 6 deals, 10 expense claims, 4 workflows, 3 scheduled jobs.

## 3. Smoke results (live staging, 2026-11-06)

`scripts/staging_smoke.py` — **31/31 passed** (p50 latency 42 ms,
max 674 ms). Run on a freshly seeded staging DB.

| # | Check | Result |
|---|---|---|
| 1 | Health 200, version 0.5.0, environment staging, DB connected | PASS |
| 2 | Staging web :3101 serves the app | PASS |
| 3–5 | Login Admin / Manager / Ops (demo accounts) | PASS |
| 6 | Wrong password → 401 | PASS |
| 7 | Instruct EN: 12 pending invoices, 581,100.19 SAR, confidence 1.00 | PASS |
| 8 | Instruct AR: same 12 invoices | PASS |
| 9 | Out-of-scope → ESCALATED, no tools | PASS |
| 10–13 | 4 workflow runs → AWAITING_APPROVAL | PASS |
| 14 | Approvals queue lists the invoice run approval | PASS |
| 15 | Manager approves invoice report | PASS |
| 16 | Double-approve → 409 | PASS |
| 17–19 | Export PDF (4,214 B, `%PDF`) / CSV (1,399 B) / XLSX (5,886 B) | PASS |
| 20 | Ops approve → 403 | PASS |
| 21 | Ops GET /admin/users → 403 | PASS |
| 22 | PDF upload match → MATCHED | PASS |
| 23 | PDF upload mismatch (99,999.99) → MISMATCHED | PASS |
| 24 | Schedules list: 3 locked jobs | PASS |
| 25 | Schedule run-now (Admin) creates a run | PASS |
| 26 | No scheduled auto-fire (scheduler OFF) | PASS |
| 27 | Evals run: **12/12 PASS** | PASS |
| 28 | Admin users list: 3 seeded users | PASS |
| 29 | Admin audit log readable | PASS |
| 30 | Manager GET /admin/users → 403 | PASS |
| 31 | n8n webhook without secret → 503 (disabled) | PASS |

Scheduler OFF — verified two ways: `SCHEDULER_ENABLED=false` loads
from `.env.staging`, and the staging `scheduled_jobs.next_run_at`
values stayed at the seed placeholder (2026-11-07 00:00:00) while
dev's were refreshed by its running scheduler to the real next fire
times (Nov 7 05:00, Nov 9 06:00 Monday, Dec 1 06:00 UTC).

Visual check (Playwright headless shell, 1280×900, Manager login):
landing (v0.5.0 badge, "API online — v0.5.0 · DB connected", "agent is
live" copy), login, approvals ("Export invoice report as PDF
(12 invoices, 581,100.19 SAR)", 37 pending), workflows, schedules —
all render with real data, one-line header, no Roman Urdu (text scan
0 matches; tesseract OCR over the screenshots 0 matches).
Screenshots: `/tmp/p2shots-staging/`.

Dev re-verification after the v0.5.0 bump: pytest **105 passed**;
dev backend restarted on v0.5.0 (health 200, development, DB
connected); dev login + instruct live (12 pending, 581,100.19 SAR,
confidence 1.00). Dev database restored to the seed baseline
(3 users, 24 invoices, 0 runs, 0 approvals) after the pytest run —
pytest leaves run/approval rows behind (known observation from
TESTING.md section 7).

## 4. Changes in v0.5.0 (staging only)

- `backend/app/core/config.py`: version 0.5.0; `AMH_ENV_FILE` selects
  the env file (default `.env`); `scheduler_enabled` setting
  (default true); `n8n_webhook_secret` now reads the documented
  `AMH_N8N_WEBHOOK_SECRET` name — pydantic-settings 2.5.2 uses only
  the first `AliasChoices` entry as the env var name, so the alias
  is ordered with the documented name first. (Before this fix the
  `.env.example` variable was silently ignored; the webhook tests
  set the field directly, so they never caught it.)
- `backend/app/main.py`: the scheduler starts only when
  `scheduler_enabled` is true.
- `frontend/vite.config.ts`: `/api` proxy target from `AMH_API_TARGET`
  (default dev :8100), applied to both dev server and preview.
- `frontend/package.json`: version 0.5.0; `build:staging` (→
  `dist-staging`) and `preview:staging` (:3101) scripts.
- `frontend/src/App.tsx`: `APP_VERSION` 0.5.0.
- `tests/test_health.py`: version assertion 0.4.0 → 0.5.0.
- New: `.env.staging`, `scripts/staging_setup.{sh,ps1}`,
  `staging_start.{sh,ps1}`, `staging_start_web.{sh,ps1}`,
  `staging_build_web.{sh,ps1}`, `staging_stop.{sh,ps1}`,
  `scripts/staging_smoke.py`, this document.
- `.gitignore`: `frontend/dist-staging/` and `data-staging/` added
  (`.env.*` was already ignored, so `.env.staging` never goes to git).

## 5. Still 501 (honest, unchanged from Testing)

- `POST / PUT / DELETE /api/v1/schedules` (create/update/delete)
- `POST /api/v1/auth/register` (Admin creates users)
- `POST /api/v1/agent/runs/{id}/cancel`
- Agent long-term memory recall (pgvector similarity)
- Parallel multi-agent execution

## 6. Promotion checklist (Production)

Nothing here is production yet. Before Production, each item must be
done and re-verified — do not promote by copying staging as-is:

- [ ] Demo accounts OFF — production refuses demo logins
      (`environment == "production"` check in `auth.py` already
      exists; verify with a demo login attempt → 401).
- [ ] First Admin creation script — `scripts/create_admin.py`
      (production must not seed demo users; seed script must not run
      against the production database).
- [ ] Fresh production JWT secret (64 hex, new — never reuse the
      staging secret) in `.env.production`; weak-secret fail-fast
      already exists in `security.py` (production only).
- [ ] CORS restricted to the production origin only (no localhost,
      no wildcard); fail-fast on wildcard CORS.
- [ ] Rate limits verified live (login 5 failed/min, instruct +
      workflow runs 10/user/hour) — currently code-level only.
- [ ] Upload limit live-tested (10 MB; 11 MB → 413).
- [ ] Backup / restore scripts (`backup.py` / `restore.py`) written
      and live-tested on the production database.
- [ ] `scripts/healthcheck.py` extended or pointed at the production
      port (currently hardcoded to dev :8100).
- [ ] Production smoke run (same 31 checks as section 3, against
      the production ports) — all PASS before handover.
- [ ] Scheduler decision: ON in production (APScheduler in-process,
      locked jobs 08:00 / Mon 09:00 / 1st 09:00 Asia/Riyadh) —
      verify the first scheduled fire creates a run and stops at
      AWAITING_APPROVAL.
- [ ] Rollback plan written (previous version + database restore
      steps) before the first production start.
