# Sprint 3 — v0.4: Scheduler + PDF Invoice OCR + Admin + Evals

> **Note (v0.6.0):** the demo company was rebranded to Al Madar Holding with an emerald + gold theme; see [REBRAND.md](REBRAND.md).

## Summary

Sprint 3 completes the operations loop. Four areas went live:

1. **Scheduler** — APScheduler in-process, three locked jobs (Asia/Riyadh),
   plus an n8n webhook trigger.
2. **PDF invoice OCR** — upload, extract, match against the purchase order,
   flag mismatches, queue for approval.
3. **Admin** — user and role management, password resets, audit log,
   observability.
4. **Evals** — 12 scripted scenarios against the design targets.

Version: **0.4.0**. Tests: **105 passed, 0 failed** (pytest, ~65 s).
Frontend build passes. Live verification on the running backend and a
Playwright visual check of all five pages (landing, Schedules, Evals,
Workflows, Admin) — clean, no Roman Urdu anywhere.

## 1. Scheduler

APScheduler `BackgroundScheduler`, timezone Asia/Riyadh, started and
stopped with the FastAPI lifespan. The three locked jobs are seeded
(`scheduled_jobs`):

| Job | Workflow | Cron | Next run (verified) |
|---|---|---|---|
| Daily invoice check | INVOICE_REPORT | `0 8 * * *` | 2026-11-07 08:00 +03:00 |
| Weekly CRM digest | CRM_FOLLOWUP | `0 9 * * 1` | 2026-11-09 09:00 +03:00 (Monday) |
| Month-end supplier summary | SUPPLIER_FOLLOWUP | `0 9 1 * *` | 2026-12-01 09:00 +03:00 |

A scheduled run is a normal workflow run (Supervisor → Data → Report →
approval queue) executed as the Admin user with
`plan.trigger = "scheduled"` — no shortcut. A scheduled run can only
produce an approval queue entry; nothing executes on its own.

Endpoints:

- `GET /api/v1/schedules` — the three jobs with cron, next run, active flag.
- `POST /api/v1/schedules/{id}/run-now` — manual trigger (Operations Manager or
  Admin; Operations Officer gets 403). Rate limit: 10 runs per user per hour.
- `GET /api/v1/schedules/{id}/runs` — run history (manual and scheduled).
- `POST /api/v1/webhooks/n8n/trigger` — optional n8n trigger. Requires the
  `X-Webhook-Secret` header to match `AMH_N8N_WEBHOOK_SECRET`. With no
  secret configured the endpoint returns 503 (webhook disabled); a wrong
  secret returns 403. Body: `{"workflow_key": ...}` or
  `{"schedule_id": ...}`.
- `POST / PUT / DELETE /schedules` stay an honest 501 (create/update/delete
  of schedules is not in scope).

### Cron day-of-week bug found and fixed

`CronTrigger.from_crontab("0 9 * * 1")` does **not** convert crontab's
day-of-week (1 = Monday) to APScheduler's convention (0 = Monday). The
weekly job would have fired on **Tuesday**. Verified on 2026-11-06:
from Monday 2026-11-09 07:00 UTC the trigger returned Tuesday
2026-11-10 09:00 +03:00. Fix: `services/scheduler.py::_cron_trigger`
parses the 5-field crontab and converts the day-of-week field
(crontab 0/7 = Sunday → 6, 1 = Monday → 0, …), used by both the
scheduler and `next_run_after`. After the fix the weekly job's next
fire is Monday 2026-11-09 09:00 +03:00.

On startup the scheduler also refreshes each job's stored `next_run_at`
from its cron (the seed writes a placeholder "tomorrow"; the API shows
the stored value, so it must be the real next fire time).

## 2. PDF invoice OCR

`POST /api/v1/invoices/upload` (multipart PDF, 10 MB limit) and the
same pipeline behind `POST /api/v1/workflows/{key}/attach-pdf`:

1. Extract fields (invoice number, supplier, PO number, amount, VAT,
   issue/due date) with strict regexes.
2. Match against `erp_invoices` on the PO number: supplier, amount, and
   the 15% VAT rule (`vat == round(amount * 0.15, 2)`).
3. Save the result and queue a `record_invoice` approval:
   `MATCHED` → record as PENDING; `MISMATCHED` → record as DISPUTED
   with the mismatched fields listed. Nothing is recorded until a
   manager approves.
4. Unreadable PDFs, missing PO numbers, or missing required fields
   return `EXTRACTION_FAILED` — no approval, run marked FAILED.

### PaddleOCR — honest status

PaddleOCR is the first extraction attempt, per the design, with a
PyMuPDF text-layer fallback. On this VM the status is:

- paddleocr 3.7.0 + paddlepaddle 3.3.1 install fine; models download
  fine (PP-LCNet, UVDoc, PP-OCRv6 detection/recognition).
- Inference **fails** with
  `NotImplementedError: ConvertPirAttribute2RuntimeAttribute not support
  [pir::ArrayAttribute<pir::DoubleAttribute>]` (OneDNN executor,
  paddlepaddle 3.3.1) — reproduced with file-path and numpy-array input,
  and with `FLAGS_use_mkldnn=0`. The code uses the correct PaddleOCR
  3.x API (`PaddleOCR(use_textline_orientation=True, lang="en")`,
  `predict(path)`, `rec_texts`), so it will work on a machine where
  PaddlePaddle runs.
- The live path on this VM is **PyMuPDF text-layer extraction**
  (method `pymupdf_text`). It extracts every field of a text-layer PDF
  correctly.
- **Scanned-image OCR is PC-only** until PaddlePaddle runs on the target
  machine. No scanned-image OCR is claimed.

Verification used two synthetic PDFs generated by
`scripts/generate_test_invoice.py` (from seeded PO-2026-2001):

- `invoice_match.pdf` — INV-2026-1999, same supplier/amount/VAT/PO →
  MATCHED, 0 mismatches. Live demo: approved → recorded in ERP as
  PENDING (50,580.46 SAR + 7,587.07 VAT).
- `invoice_mismatch.pdf` — amount 99,999.99 → MISMATCHED
  (`amount_sar` + `vat_15_percent` flagged).

## 3. Admin

All endpoints Admin-only (Operations Officer and Operations Manager get 403),
every action written to the audit log.

- `GET /api/v1/admin/users` — list users (id, name, email, role, created).
- `PUT /api/v1/admin/users/{email}/role` — change a role. Changing your
  own role is blocked (403).
- `POST /api/v1/admin/users/{email}/reset-password` — returns a generated
  12-character password in the response (no fake email — the Project 1
  v0.10 pattern). The admin hands it to the user out of band.
- `GET /api/v1/admin/audit` (alias `/api/v1/admin/audit-logs`) — audit log
  with `action` and `limit` filters.
- `GET /api/v1/admin/observability` — total runs, runs by status, success
  rate, latency p50/p95 over workflow steps, token total, pending
  approval count.

Live demo (admin): users listed (3), role changed on a temporary user
and restored, password reset returned a 12-character password, audit
`LOGIN` filter returned rows, observability showed 105 runs at 100%
success, p50 0 ms / p95 10 ms.

## 4. Evals

`POST /api/v1/eval/run` runs 12 of the design's 22 scenarios and stores
each result in `eval_results`; `GET /api/v1/evals/results`,
`GET /api/v1/evals/summary`, and `GET /api/v1/evals/latest` read them
back. Scenarios: invoice report totals, supplier follow-up overdue,
CRM follow-up stale leads, expense approval policy, invoice report
this month, expense second approval (temporary 12,500 SAR claim,
removed afterwards), PDF invoice match, PDF invoice mismatch,
adversarial payment (refused), adversarial injection (approves nothing),
self-check catch (tampered totals), scheduled run trigger.

Latest live run (2026-11-06, via the API): **12/12 passed** —
pass rate 1.00, tool accuracy 1.00, approval compliance 1.00,
self-check catch rate 1.00, latency p95 142 ms (design target < 60,000 ms).
Design targets met: task success ≥ 0.85, tool accuracy ≥ 0.90, approval
compliance 100%, self-check catch ≥ 0.80, escalation ≥ 0.80.

Eval scenarios look jobs up by workflow key, not by id — a re-seed
re-creates jobs with new ids, and a hardcoded id broke the scheduled-run
scenario once (caught by the live eval run: 11/12 before the fix).

## 5. Frontend

New pages: **Schedules** (three jobs, cron labels, Run now, history),
**Admin** (users table, role change, reset password shown once,
observability cards, audit log with filter), **Evals** (Run evals,
summary cards, scenario table). **Workflows** gained an "Attach invoice
PDF" section with a result panel (method, fields, match status,
mismatches, link to the approval). Nav updated (Schedules, Evals;
Admin only for ADMIN role). Landing copy fixed: the stale v0.1 text
"the agent itself arrives in Sprint 2" now reads
"v0.4.0 — the agent is live: instruct it, run a workflow, and approve
the work before anything executes."

## 6. Tests

105 passed, 0 failed (`pytest tests/ -q`, ~65 s), including new files:

- `tests/test_schedules.py` — cron math (daily/weekly/monthly next runs),
  list, run-now creates a real run + approval, 403 for Ops, 404 for
  unknown schedule, rate limit, scheduled job runs as Admin.
- `tests/test_pdf_ocr.py` — synthetic PDF extraction, PO match, mismatch
  flag, unreadable PDF, file-size limit, approval execution records the
  invoice.
- `tests/test_admin.py` — RBAC (Ops 403, Manager 403), role change works,
  self-role-change blocked, reset password, audit filter, observability
  (this test caught a real bug: `latencies` was built as ints then
  indexed with `v[0]` — fixed to query rows and take `r[0]`).
- `tests/test_evals.py` — 12 scenarios run, results stored, summary
  metrics, second run is idempotent.
- `tests/test_webhooks.py` — 503 without a secret, 403 on a wrong secret,
  200 triggers a real run, 404 unknown workflow, 400 missing target.

## 7. Bugs fixed during this sprint

1. **Cron day-of-week** (above) — the weekly CRM digest would have
   fired on Tuesdays.
2. **Observability latencies** — `TypeError: 'int' object is not
   subscriptable` in `admin.py`.
3. **Stale `next_run_at`** — scheduler startup now refreshes it from the
   cron (see section 1).
4. **Seed id drift** — `scripts/seed.py` used per-row `delete()`, so a
   re-seed gave workflows/jobs new ids and broke anything keyed on
   seeded ids. Now `TRUNCATE ... RESTART IDENTITY CASCADE`: a re-seed
   restores ids 1–4 (workflows) and 1–3 (jobs). Tests that used a
   hardcoded workflow/schedule id now look the id up by key.
5. **Test fixture cleanup** — `make_user` teardown did not delete
   `agent_memory` rows or approvals the user requested/approved, so
   throwaway users leaked (6 leftovers after one run). Fixed; a full
   run now leaves exactly the 3 seeded users.

## 8. Environment recovery (2026-11-06)

During this sprint the VM restarted: `/tmp` was wiped, the backend
server died, and PostgreSQL was gone (system files outside `~` are
ephemeral on VM replacement). Recovery: `apt` was stalled ~13 minutes
on a slow mirror (`mirror.cogentco.com` in `ubuntu.sources`) — the
sources file was rewritten to the single Azure mirror (delete +
recreate; the file is owned by `nobody`). PostgreSQL 16 + pgvector
0.6.0 reinstalled, cluster `16 main` online on 5432, database
`almadar_agent` recreated, `scripts/seed.py` re-run (3 users, 10 suppliers,
24 invoices, 8 customers, 10 leads, 6 deals, 10 expense claims,
4 workflows, 3 scheduled jobs). Sprint 2's live-demo run/approval rows
were lost with the old database; the seed baseline is restored and the
Sprint 3 demo was re-run on it. Project code in `~/workspace/` was
unaffected.

## 9. Live verification (2026-11-06, backend :8100, frontend :3100)

- Health 200, version 0.4.0, database connected.
- Schedules: 3 jobs; next runs 2026-11-07 05:00 UTC (daily),
  2026-11-09 06:00 UTC (Monday), 2026-12-01 06:00 UTC (month-end).
- Run-now (schedule 1): run created, AWAITING_APPROVAL, confidence 1.0.
- PDF upload match: MATCHED, approval created; approved → invoice
  INV-2026-1999 recorded in ERP as PENDING (50,580.46 SAR, VAT 7,587.07).
- PDF upload mismatch: MISMATCHED (amount + VAT flagged), DISPUTED
  approval created.
- Admin: role change + reset password + audit + observability (live).
- Evals via API: 12/12 PASS.
- n8n webhook without a secret: 503 (disabled, as designed).
- Rate limit observed live: a user with 10 runs in the last hour gets
  `rate_limited` on run-now (the limit works; the demo used a fresh
  user afterwards).
- Visual check (Playwright headless shell): landing, Schedules, Evals,
  Workflows (+ PDF upload section), Admin — all render correctly with
  real data; no Roman Urdu.

Final demo state left in the database: 3 users, 24 invoices, 1 run
(the demo PDF upload, AWAITING_APPROVAL), 1 pending approval
(#114, the MATCHED invoice INV-2026-1999 — ready for a manager to
approve), 12 eval result rows (12/12). Test-run byproducts were cleaned
after verification; eval results were kept.

## 10. Still 501 (honest, unchanged)

- `POST / PUT / DELETE /api/v1/schedules` (create/update/delete schedules)
- `POST /api/v1/auth/register`
- `POST /api/v1/agent/runs/{id}/cancel`
- Agent long-term memory recall (pgvector similarity)
- Parallel multi-agent execution

## 11. How to run

```bash
# Backend (from the project root)
cd backend && ../.venv/bin/python -m uvicorn app.main:app --port 8100
# Frontend preview
cd frontend && npm run preview -- --port 3100 --host 127.0.0.1
# Tests
.venv/bin/python -m pytest tests/ -q
# Evals (CLI)
.venv/bin/python scripts/run_evals.py
# Synthetic test invoices
.venv/bin/python scripts/generate_test_invoice.py
```

Demo accounts (demo only): admin@almadar.local / Admin123!,
manager@almadar.local / Manager123!, ops@almadar.local / Ops123!.
