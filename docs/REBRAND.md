# Rebrand — v0.6.0 (2026-11-06)

Project 2 now has its own identity, fully distinct from Project 1.
Project 1 keeps the bank identity; this project is a different
fictional organisation with its own name, colours, and role names.

## Why

Fahad's order (2026-11-06): Project 2 must be completely different
from Project 1 — name, colours, everything — and everything must fit
properly everywhere. The demo company is no longer a bank: it is a
Saudi business group, which fits an ERP/CRM operations agent better
than a bank does.

## Mapping — old → new

| Area | Before (v0.5.0) | After (v0.6.0) |
|---|---|---|
| Demo company | Riyadh Trust Bank | **Al Madar Holding** (fictional Saudi business group — trading, logistics, contracting) |
| Primary colour | Navy `#0B2C4A` | Emerald `#0B3D2E` |
| Accent colour | Gold `#C9A227` | Gold `#C8A24B` |
| Background | White / navy tints | White / ivory + emerald tints |
| Role | `BRANCH_MANAGER` / Branch Manager | `OPERATIONS_MANAGER` / Operations Manager |
| Demo emails | `*@rtb-agent.local` | `*@almadar.local` |
| Service name | `rtb-ai-agent` | `almadar-ai-agent` |
| Dev database | `rtb_agent` | `almadar_agent` |
| Staging database | `rtb_agent_staging` | `almadar_agent_staging` |
| Auth cookies | `rtb_access` / `rtb_refresh` | `amh_access` / `amh_refresh` |
| Env vars | `RTB_ENV_FILE`, `RTB_N8N_WEBHOOK_SECRET`, `RTB_API_TARGET` | `AMH_ENV_FILE`, `AMH_N8N_WEBHOOK_SECRET`, `AMH_API_TARGET` |
| npm package | `riyadh-trust-bank-ai-agent-web` | `almadar-ai-agent-web` |
| Version | 0.5.0 | **0.6.0** |

## What did not change

- **Behaviour is identical.** Same 4 workflows, same approval rules,
  same seed data shape (3 users, 10 suppliers, 24 invoices, 8
  customers, 10 leads, 6 deals, 10 expense claims, 4 workflows,
  3 scheduled jobs). The supplier and customer names are Saudi trading
  companies, which fit a holding group.
- **Ports are unchanged:** API :8100 / Web :3100 (dev), API :8101 /
  Web :3101 (staging).
- **Project folder name** (`riyadh-trust-bank-ai-agent`) is unchanged;
  the repository is renamed when the project is published to GitHub
  (Production gate).
- **Project 1 is untouched.** Its bank identity, navy theme, and repo
  stay exactly as they are.

## Layout fit pass (same release)

Fahad also asked that everything fit properly everywhere. The header
wrapped to two lines on the Admin page at 1024 px (7 nav links). The
fix: wider container (`max-w-7xl`), tighter nav padding, smaller
brand title, `whitespace-nowrap` on every header element. Verified:
header height is 69 px — one line — on every page, for both roles,
at 1024 px and 1280 px.

## Verification (v0.6.0)

- pytest: **105 passed**.
- Staging smoke: **31/31 passed** (API :8101 / Web :3101).
- Dev live checks: manager login (`OPERATIONS_MANAGER`), instruct EN
  (12 pending invoices, 581,100.19 SAR, confidence 1.00), workflow run
  → approval → export (PDF 4,209 bytes, new branding), evals **12/12**.
- Visual check (Playwright headless shell): landing, login, instruct,
  workflows, approvals, reports, schedules, evals, admin — all pages
  at 1280 px and 1024 px; `docs/screenshots/testing/` retaken from
  the v0.6.0 build.
- Roman Urdu scan: **0 matches** (code, docs, UI text + tesseract OCR
  on all screenshots).

## Notes from the rebrand run

- The VM was replaced mid-rebrand (system packages outside `~` do
  not survive a replacement). PostgreSQL 16 + pgvector were
  reinstalled, the two databases recreated as `almadar_agent` /
  `almadar_agent_staging`, and both re-seeded to baseline. The
  esbuild native binary also segfaulted after the replacement and
  was reinstalled (`npm install` re-fetched `@esbuild/linux-x64`
  0.21.5). No project code was lost — everything lives under
  `~/workspace`.
- `scripts/seed.py` now prints the actual database name instead of a
  hardcoded one.
