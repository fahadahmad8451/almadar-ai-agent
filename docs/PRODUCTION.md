# Production — v0.8.0 (2026-11-06)

Local production only ($0, no cloud). The production environment is a
separate PostgreSQL database (`almadar_agent_prod`) on the same machine,
served on the same ports as dev (API **8100**, web **3100**) — so the
dev servers must be stopped while production runs, and restarted
afterwards. Dev and staging data are never touched by production.

## What changed in v0.8.0

| Area | Change |
|---|---|
| Dashboard | New read-only `GET /api/v1/dashboard/summary` — every KPI straight from the database (pending invoices + total + VAT, overdue suppliers + total, pending approvals count + top 4, latest eval summary, 5 most recent runs). The Dashboard page uses it only; the v0.7.0 instruct calls and the `sessionStorage` cache are gone. No instruct budget is used, so the figures are always live. Any signed-in role may read it (officers see only their own runs/approvals). |
| Hardening | Security headers on every response (`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, basic CSP). No `Server` header (uvicorn `--no-server-header`). Fail-fast at startup in production: weak/placeholder JWT secret (< 32 chars) or wildcard CORS refuses to start. |
| Rate limits | Login: 5 failed attempts per 60 s per (IP, email) → 429 with `Retry-After`; a successful login clears the counter. Instruct + workflow runs: 10 per user per hour (unchanged). Uploads: 10 MB limit, 11 MB → 413 (unchanged, now live-tested). |
| Demo accounts | OFF in production (`environment == "production"`). Demo logins return 401, the `/health` payload reports `demo_accounts_enabled: false`, and the Login page hides its demo section. |
| Admin creation | `scripts/create_admin.py` creates users from the CLI (email / name / role / password). The first Admin is created this way. |
| Backup / restore | `scripts/backup.py` (pg_dump + `data-prod/` copy + manifest) and `scripts/restore.py` — both live-tested. `scripts/healthcheck.py` now takes `--url`, `--expect-version`, `--expect-env` and exits 0/1. |

## Production environment

`.env.production` (created by `scripts/production_setup.sh` from
`.env.production.example`, with a fresh 48-char JWT secret — never the
dev or staging secret):

| Setting | Value |
|---|---|
| `ENVIRONMENT` | `production` |
| `DATABASE_URL` | `.../almadar_agent_prod` |
| `JWT_SECRET` | fresh secret, 32+ chars (fail-fast if weak) |
| `CORS_ORIGINS` | `http://localhost:3100,http://127.0.0.1:3100` only |
| `DEBUG` | `false` (forced off in production) |
| `SCHEDULER_ENABLED` | `true` — the three locked jobs fire on schedule (daily 08:00, weekly Mon 09:00, month-end 1st 09:00, Asia/Riyadh), running as the Admin created by `create_admin.py` |
| `EXPORT_DIR` / `UPLOAD_DIR` | `./data-prod/exports`, `./data-prod/uploads` |
| `MAX_UPLOAD_MB` | `10` |

`.env.production` is git-ignored and never committed. The secret lives
only in that file.

## Start / stop

```bash
# First time only
./scripts/production_setup.sh        # creates DB, fresh secret, seeds WITHOUT demo accounts
AMH_ENV_FILE=.env.production python scripts/create_admin.py \
    --email fahad@almadar.local --name "Fahad Ahmad" --role ADMIN
# (repeat create_admin.py for a manager and an officer if needed)

# Every run
./scripts/production_start.sh        # stops dev servers (same ports), starts API :8100
./scripts/production_start_web.sh    # serves the built frontend on :3100 (npm run build first)
./scripts/production_stop.sh         # stops production API + web

# Back to dev afterwards
./scripts/dev_start.sh               # API :8100
./scripts/dev_start_web.sh           # web :3100
```

PowerShell equivalents exist for every script (`production_setup.ps1`,
`production_start.ps1`, `production_start_web.ps1`,
`production_stop.ps1`).

## Health check

```bash
python scripts/healthcheck.py --expect-version 0.8.0 --expect-env production
# OK (exit 0) — or FAIL with the reason (exit 1)
```

## Backup / restore

```bash
AMH_ENV_FILE=.env.production python scripts/backup.py
# -> backups/<UTC timestamp>/db.dump + data-prod/ + manifest.json

AMH_ENV_FILE=.env.production python scripts/restore.py backups/<timestamp> --yes
# Restores the dump (pg_restore --clean) and the data-prod/ copy,
# then prints the restored user/invoice counts for verification.
```

Backups are git-ignored (`backups/`). Keep a copy off the machine
before any risky change.

## Rollback plan

Production, staging and dev are separate databases and separate env
files, so rolling back is a stop + start, never a data migration:

1. **Stop production:** `./scripts/production_stop.sh`
2. **Go back to staging** (verify the last good build):
   `./scripts/staging_start.sh` + `./scripts/staging_start_web.sh`
   (API :8101, web :3101, DB `almadar_agent_staging`).
3. **Or go back to dev:** `./scripts/dev_start.sh` +
   `./scripts/dev_start_web.sh` (API :8100, web :3100, DB `almadar_agent`).
4. **If production data is bad:** restore the last good backup
   (`scripts/restore.py backups/<timestamp> --yes`) and re-run the
   production smoke before starting the API again.
5. **If the code is bad:** the previous version is in the zip
   `Project-2-Structure-v0.7.zip` (and the v0.7.0 staging smoke still
   passes against the staging DB). Re-extract, rebuild, re-run staging
   smoke, then promote again.

Nothing in production setup deletes dev or staging data — a rollback
never loses work from another environment.

## Promotion notes (from staging)

- Staging smoke stays green against the staging DB (31/31) — the
  production changes (dashboard endpoint, headers, rate limit) are
  additive and do not change staging behaviour, except the version
  number (0.8.0) and the `/health` payload (now reports
  `demo_accounts_enabled`).
- The production smoke (`scripts/production_smoke.py`) mirrors the
  staging smoke and adds production-only checks: demo logins → 401,
  security headers, no `Server` header, 6th failed login → 429,
  11 MB upload → 413, dashboard summary exact values.
- The rate limiter is in-memory and per-process: production runs a
  single uvicorn worker. Do not run with `--workers > 1` (there is no
  shared store, so the limit would not hold across workers).

## Still not implemented (501)

Schedule CRUD, auth register (the rate limit is ready for it when it
goes live), run cancel, long-term memory recall (pgvector), parallel
multi-agent execution.
