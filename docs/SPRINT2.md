# Sprint 2 — v0.3: Report Agent + Approval Agent + Workflows

> **Note (v0.6.0):** the demo company was rebranded to Al Madar Holding with an emerald + gold theme; see [REBRAND.md](REBRAND.md).

Sprint 2 turns the Sprint 1 instruct-only agent into a working
operations loop: a signed-in user runs a workflow, the agent gathers
the data, checks its own totals, builds a real report, and queues it
for a human manager. Nothing executes until that manager approves —
and the approval is enforced in the tool layer, not just the UI.
Every number comes from PostgreSQL; every export file is a real file.

## What is live

### Report Agent — real reports, real files

- `POST /api/v1/workflows/{key}/run` builds a report per workflow:
  - **INVOICE_REPORT** — invoice table with totals + VAT, plus a
    supplier summary (24 invoices, 1,067,465.96 SAR in the live demo).
  - **SUPPLIER_FOLLOWUP** — overdue supplier list with a reminder
    email draft per supplier, in English and Arabic.
  - **CRM_FOLLOWUP** — stale-lead digest with a follow-up draft per lead.
  - **EXPENSE_APPROVAL** — expense summary with a live policy re-check
    per claim (category limits, receipt, second-approval flag).
- Exports are real files, generated only after approval:
  `PDF` (ReportLab), `CSV`, `XLSX` (openpyxl) — recorded in
  `report_exports` and stored under `data/exports/`. `GET
  /reports/{run_id}/export?format=pdf|csv|xlsx` serves the file (or
  generates it from the run's stored report payload). An
  AWAITING_APPROVAL run returns 409 `approval_required`.
- `GET /reports` lists exports; `GET /drafts` lists email drafts.
  An Operations Officer sees only their own runs' exports and drafts.
- Arabic stays in the API and UI summaries; PDF/CSV/XLSX exports are
  rendered in English because ReportLab's built-in fonts cannot shape
  Arabic script — documented here, not hidden.

### Approval Agent + approval tokens

- The approval token is the approval row itself. A write tool
  executes only when called with the id of a PENDING approval whose
  diff contains that exact action for that run. The check lives in
  the tool registry (`execute_tool(..., approval_token=...)`) — the
  single choke point for all tool use.
- Flow: run → Approval Agent creates one approval per item (one per
  claim, one per email draft, one per report export) → queue entry
  (PENDING) → Manager approves/rejects → approve executes the diff,
  reject executes nothing.
- Endpoints: `GET /api/v1/approvals` (queue), `GET
  /api/v1/approvals/{id}`, `POST /api/v1/approvals/{id}/approve`,
  `POST /api/v1/approvals/{id}/reject {comment}`.
- Only Operations Manager / Admin may approve or reject — an Operations
  Officer gets 403, an unsigned-in caller gets 401. A second decision
  on an already-decided approval returns 409 `already_decided`.
- A write tool called without a token is recorded as a `refused`
  tool call and raises — it never executes. A token for the wrong
  run, a wrong action type, or an already-decided approval is
  refused the same way.
- Second approval (design decision): an expense claim above 10,000
  SAR can only be executed by an ADMIN. A Operations Manager approving it
  gets 403 `second_approval_required` and the approval stays pending
  for an Admin. A full two-step approval flow is deferred.
- Execution is safe to retry: every action is pre-validated before
  anything runs, and every write tool is idempotent (re-approving an
  already-approved claim, or re-exporting an already-generated file,
  returns the existing result instead of executing twice).

### Workflows run — the full pipeline

- `POST /api/v1/workflows/{key}/run` — Supervisor (plan) → Data
  Agent (tools) → Self-Check (verify totals) → Report Agent (build
  report) → Approval Agent (create approvals) → run stops at
  AWAITING_APPROVAL. All four workflows are wired: INVOICE_REPORT,
  SUPPLIER_FOLLOWUP, CRM_FOLLOWUP, EXPENSE_APPROVAL.
- Runs share the 10/hour per-user rate limit. Unknown key → 404,
  inactive workflow → 409, bad export format → 400.
- `GET /api/v1/agent/runs` and `GET /api/v1/agent/runs/{id}/trace`
  show every step, exactly like the instruct runs in Sprint 1.

### Frontend — Approvals, Workflows, Reports

- **Approvals page** — the queue with a filter (All / Pending /
  Approved / Rejected), each entry's full diff/preview (what will
  happen on approval, including the email draft body), and
  Approve / Reject buttons for managers only. Reject asks for an
  optional comment.
- **Workflows page** — the four workflow cards with an export-format
  selector (PDF/CSV/XLSX), Run button, last-run result, and the run
  history (latest 10 runs with status and confidence).
- **Reports page** — exports grouped by run with PDF/CSV/XLSX
  download buttons (real files via the backend), and the approved
  email drafts.
- A shared navigation header (Instruct / Workflows / Approvals /
  Reports) is now on all signed-in pages.

## Verification

- pytest: **66 passed** (46 from Sprint 1 + 20 new/updated for
  Sprint 2) — approval flow (approve executes + audit, reject
  executes nothing, no-token refused, Ops approve 403, double-approve
  409, high-value claim needs Admin), real export files (PDF starts
  with `%PDF`, CSV has a real header + rows, XLSX is a real
  spreadsheet), all four workflows end-to-end to AWAITING_APPROVAL.
- Live demo (backend :8100, Manager Layla Alsubaie): INVOICE_REPORT
  run #118 → 24 invoices, 1,067,465.96 SAR (VAT 160,119.90 SAR),
  confidence 1.00 → approval #87 → approve → export #21
  (`run_118_invoice_report_20261106124652.pdf`, 6,191 bytes) →
  run COMPLETED. SUPPLIER_FOLLOWUP run #119 → 3 approvals → reject
  one (no draft saved), approve the other two → 2 APPROVED drafts
  saved (Kingdom Catering, Golden Falcon Transport). CSV and XLSX
  downloads verified with real rows.
- Frontend build passes (`tsc -b && vite build`), preview serves on
  :3100, bundle contains the new pages.
- Language scan: 0 non-English matches across backend, frontend, and docs.

## What is still 501

- Scheduler (`POST /api/v1/schedules`, `POST
  /api/v1/workflows/{key}/attach-pdf`), admin endpoints, and evals.
  These arrive in Sprint 3 with PDF invoice reading (OCR → PO
  match), scheduled workflow runs, the Admin page, and the eval suite.

## Notes

- `data/exports/` is gitignored; export files live on disk and are
  recorded in `report_exports`.
- The `approval_agent` execution step is recorded as a workflow step,
  so the trace shows who approved and what executed.
- `SessionLocal` runs with `autoflush=False`: `reject_approval`
  flushes explicitly before counting the remaining PENDING approvals
  (a missing flush left a rejected run at AWAITING_APPROVAL — caught
  by the reject test in this sprint).
