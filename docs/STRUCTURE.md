# Structure — v0.7.0 (2026-11-06)

## What changed

**v0.9.0 (Monitoring, last step):** request metrics + alerts in
PostgreSQL (`request_metrics`, `alerts`), six locked alert rules
with a 5-minute scheduler check (production only), an Admin-only
Monitoring page (`/monitoring`, new sidebar nav item), a daily
report script, and rotating file logs (5 MB, 5 backups). See
`docs/MONITORING.md`. The backend API is otherwise unchanged.

v0.7.0 rebuilds the whole frontend on the **Sidebar console** structure
(Demo 1 of the three theme demos shown to the product owner on
2026-11-06). The backend API is unchanged; only the presentation layer
moved.

| Area | Before (v0.6.0) | After (v0.7.0) |
|---|---|---|
| App shell | Top navigation bar (Project 1 pattern) + landing hero page | Dark emerald sidebar (full height) on every signed-in page; no landing page |
| Home after login | Landing hero (`/`) | **Dashboard** (`/dashboard`) with live KPIs |
| Navigation | Top nav links | Sidebar sections: Workspace (Dashboard, Instruct, Workflows, Approvals with live pending badge, Reports) and Manage (Schedules, Evals, Admin for admins only) |
| Top bar | Part of the header | Page title + org crumb, search box, approvals bell with pending dot |
| Login | Centered card on a light page | Centered card on a dark emerald page with Al Madar branding |
| Content background | Emerald tint (`emerald-50`) | Ivory `#F7F5F0` with bordered white cards (`#EAE5D9`, 14px radius) |

## Why

The v0.6.0 rebrand changed the name and colours, but the layout still
followed Project 1's structure (hero + top nav + cards). The product
owner asked for the structure itself to be different — a console the
operations team lives in, not a marketing-style landing page. The
sidebar console is the enterprise-operations pattern (SAP / Salesforce
style): navigation is always visible, the dashboard is the home, and
the pending-approval count is visible on every screen.

## Dashboard KPIs — all live

**v0.8.0 (Production):** the Dashboard reads every figure from ONE
read-only call, `GET /api/v1/dashboard/summary`, computed straight
from the database — pending invoices (count, total, VAT), overdue
suppliers (count, total, names), pending approvals (count + top 4),
the latest eval summary, and the 5 most recent runs. Any signed-in
role may read it (officers see only their own runs and approvals).
It uses **no agent run and no instruct budget**, so the figures are
always live — the "Refresh figures" button just re-fetches. No KPI
is hardcoded. The v0.7.0 design (two instruct calls + a
`sessionStorage` cache, with an honest "Live figures unavailable"
note once the 10-runs-per-hour budget was gone) is replaced by this
endpoint; see `docs/PRODUCTION.md` for the change.

The top-bar search sends its query to the Instruct page (`/instruct?q=…`),
which prefills the instruction box.

## Layout fit

- Sidebar is 248px (220px below the `lg` breakpoint) and sticky; the
  header is one line on every page at 1280px and 1024px.
- KPI cards are a 4-column grid at `xl`, 2 columns below that.
- The two-column dashboard panels stack below `xl`.
- The Login page has no sidebar — a centered card only.
- Mobile (<768px) is not a design target for this release: the sidebar
  stays visible and the content scrolls horizontally only in the
  narrowest tables. Desktop 1024px and up is verified.

## Verification (v0.7.0)

- pytest: **105 passed, 0 failed** (backend unchanged except the version bump).
- Staging smoke: **31/31 passed** (API :8101 / web :3101).
- Dev live check: login as Operations Manager → instruct (12 pending
  invoices, 581,100.19 SAR, confidence 1.00) → workflow run
  (AWAITING_APPROVAL) → approve (1 action executed, run COMPLETED) →
  PDF export (200, 4,208 bytes, real `%PDF`).
- Visual check (Playwright headless shell): 9 pages at 1280px
  (login, dashboard, instruct, workflows, approvals, reports,
  schedules, evals, admin) plus dashboard and admin at 1024px — all
  clean, real data, no wrapping or overflow. Screenshots in
  `~/workspace/your_files/Project-2-Screenshots-v0.7/`.
- Roman Urdu scan: 0 matches (text wordlist + tesseract OCR on all
  screenshots).
- Deleted: `frontend/src/components/Nav.tsx` and
  `frontend/src/pages/Landing.tsx` (recoverable trash, 30 days).

## Still 501

Schedule CRUD, auth register, run cancel, agent long-term memory
recall (pgvector), parallel multi-agent execution.
