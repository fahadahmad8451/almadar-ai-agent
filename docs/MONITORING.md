# Monitoring — v0.9.0 (Project 2, LAST step)

Project 2 is now complete end-to-end: Requirements → Estimate →
Design → Setup → Development (Sprints 1–3) → Testing → Staging →
Production → **Monitoring**.

Monitoring here is **local-first, $0, no external service**: no
Grafana Cloud, no PagerDuty, no Sentry SaaS, no Telegram bot.
Metrics and alerts live in PostgreSQL (`request_metrics`, `alerts`),
and the Admin sees them on the **Monitoring** page (`/monitoring`,
Admin only). If nobody looks at the dashboard, nobody is paged —
that is the honest limit of a $0 setup (see §6 for what external
alerting would need).

## 1. What is monitored

Every request the API serves is recorded by middleware
(`app/main.py`) into **`request_metrics`**: timestamp, endpoint
(id-like segments collapsed to `{id}`), method, HTTP status, latency
in ms, and the caller's role (decoded from the access token; public
requests have no role). No instruction text, no user content, no
tokens, no passwords are ever recorded. The write uses its own DB
session and is fail-open — a metrics failure is logged and never
breaks the request being measured.

Sources the dashboard and reports combine:

| Source | What it tells us |
|---|---|
| `request_metrics` | Requests, error rate, latency p50/p95 (all + instruct), top endpoints, per-hour buckets, per-role counts |
| `workflow_runs` | Runs by status, runs in the last 24 h, escalations, average confidence |
| `approvals` | Pending / approved / rejected counts |
| `eval_results` | Latest suite pass rate and failures |
| `alerts` | Alerts fired, resolved or still active |
| `/api/v1/health` | API up/down, uptime, database state |
| `scheduled_jobs` | Missed scheduled fires |

Endpoints (all ADMIN only — other roles get 403, signed-out users
get 401, exactly like the other admin routes):

| Endpoint | Returns |
|---|---|
| `GET /api/v1/admin/metrics/summary?hours=24` | Last 24 h + totals: requests, 5xx rate, latency p50/p95 (all + instruct), by endpoint/status/role, runs, escalations, confidence, approvals, latest evals |
| `GET /api/v1/admin/metrics/timeseries?hours=24` | Per-hour buckets (requests, 5xx, instructs, p95) for the last N hours (1–168) |
| `GET /api/v1/admin/monitoring/overview` | Health + summary + scheduler state + disk usage + data-dir size + active alerts + 5 newest 5xx |
| `GET /api/v1/admin/monitoring/recent-errors?limit=20` | Newest 5xx requests |
| `GET /api/v1/admin/alerts?status=active` | Alerts, newest first |
| `POST /api/v1/admin/alerts/{id}/resolve` | Mark an alert resolved (records who and when; audited as ALERT_RESOLVE) |
| `GET /api/v1/admin/monitoring/daily-reports` | Daily reports on disk + the newest report's Markdown |

## 2. Alert rules

Rules live in `backend/app/services/monitoring.py` (pure evaluation
over a DB session — tests feed them real rows and prove each rule
fires AND stays silent below its threshold). The checker is
`scripts/monitor_check.py` and the in-process scheduler job
(every 5 minutes, production only).

| Rule | Threshold | Severity | What to do |
|---|---|---|---|
| `instruct_p95_latency` | Instruct p95 latency > 500 ms over the last hour (min 5 samples) | MEDIUM | Instruct runs are rule-parser fast (~150 ms) on this VM; a p95 over 500 ms means the agent path slowed down (database contention or a slow tool). Check Recent errors + the run trace of the slowest runs. |
| `error_rate_5xx` | 5xx rate > 5% over the last hour (min 20 requests) | HIGH | Check Recent errors + `logs/app.log`; find the failing endpoint and when it first failed. |
| `eval_suite_fail` | Any scenario FAIL in the latest eval suite | HIGH | Run the evals again from the Evals page; a failing scenario names the workflow that regressed. Do not ship until the suite is green. |
| `pending_approvals_backlog` | Pending approvals > 50 | MEDIUM | Managers need to work through the queue — the Approvals page lists the oldest first. The count includes seeded/demo approvals; approve or reject them, don't just resolve the alert. |
| `scheduler_missed_fire` | An active job whose `next_run_at` passed more than 5 minutes ago (only checked while the scheduler is running) | HIGH | Check the API log for scheduler errors and that the scheduler is Running on the Monitoring page. A missed daily 08:00 invoice check can be re-run with "Run now" on the Schedules page. |
| `api_down` | Health endpoint unreachable | CRITICAL | Restart the API (`scripts/production_start.sh`). If it fails to start, read the startup error — a weak SECRET_KEY or wildcard CORS refuses to start by design. |
| `database_unavailable` | Database probe query fails | CRITICAL | Check PostgreSQL is running (`pg_ctlcluster 16 main start`); if the VM was replaced, recreate the databases and re-seed (see docs/PRODUCTION.md rollback notes). |

**Dedup:** the same rule does not create a second ACTIVE alert
inside 30 minutes (the checker reports the existing one instead).
**Auto-resolve:** when a rule's condition clears, its ACTIVE alerts
are resolved automatically on the next check. Resolving an alert by
hand records who did it — it does **not** fix the problem; if the
condition is still true, the next check fires it again (after the
dedup window).

**Exit codes of `monitor_check.py`:** 0 = healthy, no active
alert; 1 = at least one active alert (HIGH/MEDIUM); 2 = CRITICAL
alert active, or the API/database is down.

## 3. Scheduler — every 5 minutes (check) + daily (report)

The in-process APScheduler registers the alert check when
`MONITORING_ALERTS_ENABLED=true` (`.env.production` only — staging
and dev default OFF, so a stale staging database never raises
alerts nobody is watching). It probes the health endpoint and
evaluates all six rules; the job is `monitoring-alert-check`.

This VM does **not** create a scheduled task — Fahad's PC is a
different machine. Set it up there:

**Windows — Task Scheduler (PowerShell, run as Administrator):**

```powershell
# Every 5 minutes: alert check (production API :8100)
$action = New-ScheduledTaskAction -Execute "C:\path\to\venv\Scripts\python.exe" `
  -Argument "scripts\monitor_check.py --api-url http://127.0.0.1:8100" `
  -WorkingDirectory "C:\path\to\almadar-ai-agent"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName "AMH Monitor Check" -Action $action -Trigger $trigger

# Daily 08:00: daily report
$action2 = New-ScheduledTaskAction -Execute "C:\path\to\venv\Scripts\python.exe" `
  -Argument "scripts\daily_report.py" `
  -WorkingDirectory "C:\path\to\almadar-ai-agent"
$trigger2 = New-ScheduledTaskTrigger -Daily -At 08:00
Register-ScheduledTask -TaskName "AMH Daily Report" -Action $action2 -Trigger $trigger2
```

**Linux — cron:**

```cron
*/5 * * * * cd ~/almadar-ai-agent && AMH_ENV_FILE=.env.production ~/venv/bin/python scripts/monitor_check.py --api-url http://127.0.0.1:8100 >> logs/monitor.log 2>&1
0 8 * * * cd ~/almadar-ai-agent && AMH_ENV_FILE=.env.production ~/venv/bin/python scripts/daily_report.py >> logs/monitor.log 2>&1
0 3 * * 0 cd ~/almadar-ai-agent && AMH_ENV_FILE=.env.production ~/venv/bin/python scripts/rotate_logs.py >> logs/monitor.log 2>&1
```

Staging equivalent: `AMH_ENV_FILE=.env.staging` with `--api-url
http://127.0.0.1:8101`.

## 4. Daily report

`scripts/daily_report.py` builds a summary of one calendar day
(UTC; `--date YYYY-MM-DD`, default yesterday) from the real
database — requests, 5xx, latency p50/p95 (all + instruct), top
endpoints, runs by status, approvals approved/rejected/pending,
evals, alerts fired — and writes it to
`<data-dir>/reports/daily-YYYY-MM-DD.json` and `.md`. Counts only —
no instruction text, no PII. No email is sent (there is no SMTP);
the report is a file, and the Monitoring page shows the newest one.

## 5. Log rotation and retention

- The application log is `logs/app.log` in the environment's data
  directory (`data/logs`, `data-staging/logs`, `data-prod/logs`),
  written through a `RotatingFileHandler`: **max 5 MB, 5 backups**
  (about 30 MB total). Rotation is automatic; the live file is
  never deleted by hand.
- `scripts/rotate_logs.py` (run weekly, or by hand) archives
  rotated backups older than **7 days** into
  `logs/archives/app-YYYYMMDD-HHMMSS.log.gz` and deletes archives
  older than **30 days**. Nothing is deleted before it is archived.
- Request metrics and alerts are database rows, not files: they
  grow by roughly one row per request. If the table ever needs
  trimming, delete rows older than 90 days in a maintenance window
  (`DELETE FROM request_metrics WHERE created_at < now() - interval
  '90 days'`) — alerts are kept indefinitely, they are the audit
  record of what went wrong.

## 6. What monitoring does NOT do (honest limits)

- **No external alerting.** Nobody is woken up at night: no email,
  SMS, phone call or Telegram message. To add it you would need an
  SMTP account (email), a Twilio-style account (SMS, paid), or a
  Telegram bot token + chat id (free, but the bot must run
  somewhere). The alerts table already has everything such a sender
  would need (rule, severity, message, timestamp).
- **No uptime history beyond the database.** Uptime is "seconds
  since this process started"; a restart resets it. The
  request_metrics table is the real record of when the API was
  serving.
- **p95 on tiny samples is noisy.** The instruct-p95 rule requires
  at least 5 samples in the last hour; with few instructs a single
  slow run moves the percentile. Treat a p95 alert on <10 samples
  as "check, don't panic".
- **Alerts are only as good as the checker running.** If the
  scheduler job is off (staging/dev) or the scheduled task is not
  set up on Fahad's PC, no alert will ever fire — the dashboard
  will simply show old data. Check the "Alert checks ON/OFF" line
  on the Monitoring page.
- **The pending-approvals rule counts seeded history.** The
  production database carries approvals from verification traffic;
  the backlog alert fires on the total, not only on new items.
  Work through the queue instead of resolving the alert.

## 7. Live verification (this VM, 2026-11-06)

- **Pytest: 139 passed, 0 failed** — 121 previous + 18 new
  `tests/test_monitoring.py` (middleware recording, summary auth
  403/401, timeseries + overview shape, every rule firing AND below
  threshold, 30-minute dedup, resolve endpoint, daily-report
  builder, log rotation).
- **Frontend builds PASS** (dev + staging + production, zero tsc
  errors; the Monitoring page is in all three).
- **Staging smoke: 31/31 PASS** (API :8101 + web :3101, v0.9.0).
- **Live production API :8100 + web :3100**, real traffic via the
  production smoke (**41/41 PASS**): demo logins → 401, login rate
  limit 6th attempt → 429, login × 3, dashboard summary (12 pending
  invoices, 581,100.19 SAR; 3 overdue suppliers), instruct EN + AR,
  workflow runs, approval + double-approve 409, exports PDF/CSV/XLSX,
  PDF upload match + mismatch + 11 MB → 413, schedule run-now, evals
  **12/12 PASS**, admin users/audit, n8n webhook → 503.
- **1 REAL alert fired:** `[MEDIUM] pending_approvals_backlog`
  (pending approvals **74**, threshold 50 — the production smoke's
  workflow runs and evals pushed the queue from 37 to 74; the v0.8.0
  verification had already left 37 pending). `monitor_check.py`
  exit 1. A second check created NO duplicate (30-minute dedup —
  alerts table stayed at 1 row).
- **Alert resolved by hand** via the Monitoring page (Admin,
  resolved_at recorded, audited as ALERT_RESOLVE). Because the
  backlog itself was still 74, the 5-minute scheduler job honestly
  **re-fired the alert at 17:59:20 UTC** (alert #2, ACTIVE) — the
  condition is still true, and resolving the alert does not clear
  the queue. Managers need to work through the 74 pending approvals.
- **Daily report written:** `data-prod/reports/daily-2026-11-06.md`
  (+ `.json`) — 43 requests, 1 5xx (2.33%, the n8n 503), latency
  p50 9 ms / p95 450 ms, instruct p50 134 ms / p95 187 ms, 40 runs
  (30 AWAITING_APPROVAL, 10 COMPLETED), approvals 2 approved /
  74 pending, evals 24/24 passed, 1 alert.
- **Metrics summary (live, at resolve time):** 53 requests in
  24 h, latency p50 24 ms / p95 468 ms, instruct p95 187 ms,
  40 runs, 74 pending approvals, evals 12/12 (100%).
- **Rotation live:** `scripts/rotate_logs.py` run against
  `data-prod/logs` — "archived 0, deleted 0" (`app.log` under
  5 MB, nothing to rotate; rotation itself is proven by pytest
  with synthetic files).
- **Monitoring page screenshot:** `docs/screenshots/06-monitoring.png`
  — production, real cards (46 requests, instruct p95 187 ms,
  74 pending, evals 100.0%), hourly bar chart, alerts table with
  the live backlog alert + Resolve button, daily report rendered.
- **Passwords:** the production smoke needed the three prod
  accounts; their password hashes were backed up, temporary
  passwords set for the verification, then the original hashes
  restored byte-identical (verified) and the backup deleted. The
  temporary passwords now return 401.
- **Cleanup:** production stopped afterwards; dev (:8100/:3100)
  and staging (:8101/:3101) restarted and healthy. Metrics,
  alerts and the daily report were KEPT in the production
  database: they are the honest record of this verification
  traffic.
## 8. Project 2 — final PC-only pending list

These were never DONE on this VM and are still waiting on Fahad's PC
(from Testing / Staging / Production, unchanged by Monitoring):

1. **Ollama + llama3.1:8b / qwen2.5:7b** — install on the PC; until
   then the agent runs on its rule parser (confidence 1.0 on
   in-scope instructions, which is why evals pass here).
2. **Long-term memory recall (pgvector)** — the table and embedding
   column exist; similarity recall is still 501.
3. **Parallel multi-agent execution** — the supervisor runs
   sub-agents sequentially; parallel dispatch is still 501.
4. **Schedule CRUD, auth register, run cancel** — still 501.
5. **Instruct latency on the PC** — the 500 ms p95 alert threshold
   was set against this VM's ~150–210 ms rule-parser latency; with
   a real local LLM the number will be higher and the threshold may
   need revisiting.
6. **External alerting** — see §6; needs an SMTP account or a
   Telegram bot if Fahad ever wants to be paged.

Everything else in the process is DONE: Requirements, Estimate,
Design, Setup, Sprints 1–3, Testing, Staging, Production,
Monitoring. **Project 2 is complete on this VM; the 6 items above
are the PC handover list.**
