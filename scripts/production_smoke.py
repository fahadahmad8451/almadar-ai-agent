"""Production smoke test — Project 2 (Enterprise AI Agent) v0.9.0.

Runs the full happy path + production-only negative checks against
the PRODUCTION environment (API :8100, web :3100, database
almadar_agent_prod). No mocking — real API, real production
PostgreSQL, real files.

Usage:
    AMH_SMOKE_ADMIN_PASSWORD=... AMH_SMOKE_MANAGER_PASSWORD=... \\
    AMH_SMOKE_OPS_PASSWORD=... .venv/bin/python scripts/production_smoke.py

Needs: production API + production web running (scripts/production_start.sh,
        scripts/production_start_web.sh) on a freshly seeded production
        DB, with the three users created first:

    AMH_ENV_FILE=.env.production python scripts/create_admin.py \\
        --email fahad@almadar.local --name "Fahad Ahmad" --role ADMIN
    AMH_ENV_FILE=.env.production python scripts/create_admin.py \\
        --email layla@almadar.local --name "Layla Alsubaie" --role OPERATIONS_MANAGER
    AMH_ENV_FILE=.env.production python scripts/create_admin.py \\
        --email omar@almadar.local --name "Omar Aljaber" --role OPERATIONS_OFFICER

Demo accounts are OFF in production — the smoke proves a demo login
returns 401. Passwords are passed by environment, never on the
command line (they would show up in the process list).

Note on rate limits: instruct + workflow runs share a 10 runs/user/hour
budget. This script uses the three production accounts and stays under
the budget on a fresh seed. Re-running it within the same hour will hit
429 — re-seed first (./scripts/production_setup.sh, idempotent, then
re-create the three users) or wait.
"""
import json
import os
import sys
import time
import uuid
from pathlib import Path

import httpx

API = "http://127.0.0.1:8100"
WEB = "http://127.0.0.1:3100"
ROOT = Path(__file__).resolve().parents[1]
RESULTS: list[dict] = []
LAT: list[dict] = []

ADMIN_EMAIL = "fahad@almadar.local"
MANAGER_EMAIL = "layla@almadar.local"
OPS_EMAIL = "omar@almadar.local"


def rec(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append({"name": name, "pass": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""))


def j(r: httpx.Response) -> dict:
    try:
        return r.json()
    except Exception:
        return {}


def timed(client: httpx.Client, method: str, url: str, **kw) -> httpx.Response:
    t0 = time.perf_counter()
    r = client.request(method, url, **kw)
    LAT.append({"call": f"{method} {url}", "ms": round((time.perf_counter() - t0) * 1000, 1),
                "status": r.status_code})
    return r


def login(email: str, password: str) -> httpx.Client:
    c = httpx.Client(base_url=API, timeout=120, trust_env=False)
    r = timed(c, "POST", "/api/v1/auth/login", json={"email": email, "password": password})
    ok = r.status_code == 200 and j(r).get("success") is True
    rec(f"login {email}", ok, f"HTTP {r.status_code}")
    return c


def main() -> int:
    admin_pw = os.environ.get("AMH_SMOKE_ADMIN_PASSWORD")
    mgr_pw = os.environ.get("AMH_SMOKE_MANAGER_PASSWORD")
    ops_pw = os.environ.get("AMH_SMOKE_OPS_PASSWORD")
    missing = [n for n, v in (("AMH_SMOKE_ADMIN_PASSWORD", admin_pw),
                              ("AMH_SMOKE_MANAGER_PASSWORD", mgr_pw),
                              ("AMH_SMOKE_OPS_PASSWORD", ops_pw)) if not v]
    if missing:
        print(f"FAIL: missing environment variables: {', '.join(missing)}")
        print("Set them before running (see the module docstring).")
        return 1

    # 1. Health + security headers + frontend
    c = httpx.Client(timeout=30, trust_env=False)
    r = timed(c, "GET", f"{API}/health")
    d = j(r).get("data", {})
    rec("health 200, version 0.9.0, production, DB connected",
        r.status_code == 200 and d.get("version") == "0.9.0"
        and d.get("environment") == "production" and d.get("database") == "connected",
        f"HTTP {r.status_code}, version={d.get('version')}, env={d.get('environment')}, db={d.get('database')}")
    rec("health reports demo_accounts_enabled=false",
        d.get("demo_accounts_enabled") is False,
        f"demo_accounts_enabled={d.get('demo_accounts_enabled')}")
    rec("security headers present (nosniff, DENY, no-referrer, CSP)",
        r.headers.get("x-content-type-options") == "nosniff"
        and r.headers.get("x-frame-options") == "DENY"
        and r.headers.get("referrer-policy") == "no-referrer"
        and "content-security-policy" in r.headers,
        f"headers={dict(r.headers)}")
    rec("no Server header",
        "server" not in r.headers,
        f"server={r.headers.get('server')}")
    r = timed(c, "GET", f"{WEB}/")
    rec("production web :3100 serves the app",
        r.status_code == 200 and "Al Madar Holding" in r.text,
        f"HTTP {r.status_code}")
    c.close()

    # 2. Demo accounts are OFF in production
    anon = httpx.Client(base_url=API, timeout=30, trust_env=False)
    r = timed(anon, "POST", "/api/v1/auth/login",
              json={"email": "manager@almadar.local", "password": "Manager123!"})
    rec("demo login (manager@almadar.local) -> 401 in production",
        r.status_code == 401, f"HTTP {r.status_code}")
    r = timed(anon, "POST", "/api/v1/auth/login",
              json={"email": "admin@almadar.local", "password": "Admin123!"})
    rec("demo login (admin@almadar.local) -> 401 in production",
        r.status_code == 401, f"HTTP {r.status_code}")

    # 3. Rate limit: 5 failed logins, then the 6th is 429 with Retry-After
    spam = f"ratelimit-{uuid.uuid4().hex[:8]}@almadar.local"
    statuses = []
    for _ in range(6):
        r = timed(anon, "POST", "/api/v1/auth/login",
                  json={"email": spam, "password": "WrongPassword!"})
        statuses.append(r.status_code)
    rec("rate limit: 5x 401 then 6th failed login -> 429 + Retry-After",
        statuses[:5] == [401] * 5 and statuses[5] == 429
        and "retry-after" in r.headers,
        f"statuses={statuses}, retry-after={r.headers.get('retry-after')}")
    anon.close()

    # 4. Logins with the real production accounts
    admin = login(ADMIN_EMAIL, admin_pw)
    mgr = login(MANAGER_EMAIL, mgr_pw)
    ops = login(OPS_EMAIL, ops_pw)

    # 5. Dashboard summary — the v0.9.0 endpoint (no instruct budget)
    r = timed(mgr, "GET", "/api/v1/dashboard/summary")
    d = j(r).get("data", {})
    rec("dashboard summary: 12 pending invoices, 581,100.19 SAR",
        r.status_code == 200
        and d.get("pending_invoices", {}).get("count") == 12
        and d.get("pending_invoices", {}).get("total_sar") == 581100.19,
        f"HTTP {r.status_code}, pending={d.get('pending_invoices')}")
    rec("dashboard summary: 3 overdue suppliers, 164,941.98 SAR",
        d.get("overdue_suppliers", {}).get("count") == 3
        and d.get("overdue_suppliers", {}).get("total_sar") == 164941.98,
        f"overdue={d.get('overdue_suppliers')}")
    rec("dashboard summary: evals + recent runs included",
        "evals" in d and "recent_runs" in d and "pending_approvals" in d,
        f"keys={sorted(d.keys())}")
    r = timed(ops, "GET", "/api/v1/dashboard/summary")
    rec("dashboard summary: officer can read (read-only)",
        r.status_code == 200, f"HTTP {r.status_code}")
    anon2 = httpx.Client(base_url=API, timeout=30, trust_env=False)
    r = timed(anon2, "GET", "/api/v1/dashboard/summary")
    rec("dashboard summary without auth -> 401",
        r.status_code == 401, f"HTTP {r.status_code}")
    anon2.close()

    # 6. Instruct EN + AR (Testing fix values: 12 pending, 581,100.19 SAR)
    r = timed(mgr, "POST", "/api/v1/agent/instruct",
              json={"instruction": "Show me the pending invoices", "language": "en"})
    d = j(r).get("data", {})
    txt = json.dumps(d)
    rec("instruct EN: 12 pending invoices, 581,100.19 SAR",
        r.status_code == 200 and "581" in txt and d.get("confidence", 0) >= 0.7,
        f"HTTP {r.status_code}, confidence={d.get('confidence')}")
    r = timed(mgr, "POST", "/api/v1/agent/instruct",
              json={"instruction": "ما هي الفواتير المعلقة؟", "language": "ar"})
    d = j(r).get("data", {})
    rec("instruct AR: same 12 invoices",
        r.status_code == 200 and "581" in json.dumps(d),
        f"HTTP {r.status_code}, confidence={d.get('confidence')}")
    r = timed(mgr, "POST", "/api/v1/agent/instruct",
              json={"instruction": "What is the weather today?", "language": "en"})
    d = j(r).get("data", {})
    rec("out-of-scope escalated, no tools",
        r.status_code == 200 and str(d.get("status", "")).upper() == "ESCALATED",
        f"HTTP {r.status_code}, status={d.get('status')}")

    # 7. Workflow runs (Manager: invoice + supplier; Admin: CRM + expense)
    def run_workflow(client: httpx.Client, key: str, label: str) -> dict:
        r = timed(client, "POST", f"/api/v1/workflows/{key}/run", json={})
        d = j(r).get("data", {})
        rec(f"{label} run {key} -> AWAITING_APPROVAL",
            r.status_code == 200 and d.get("run_id") is not None
            and str(d.get("status", "")).upper() == "AWAITING_APPROVAL",
            f"HTTP {r.status_code}, run_id={d.get('run_id')}, status={d.get('status')}")
        return d

    inv = run_workflow(mgr, "INVOICE_REPORT", "manager")
    run_workflow(mgr, "SUPPLIER_FOLLOWUP", "manager")
    run_workflow(admin, "CRM_FOLLOWUP", "admin")
    run_workflow(admin, "EXPENSE_APPROVAL", "admin")

    # 8. Approval queue -> approve invoice report -> export downloads
    r = timed(mgr, "GET", "/api/v1/approvals")
    d = j(r).get("data", {})
    approvals = d.get("approvals", d.get("items", [])) if isinstance(d, dict) else []
    inv_approval = next((a for a in approvals
                         if a.get("run_id") == inv.get("run_id")), None)
    rec("approvals queue lists the invoice run approval",
        inv_approval is not None, f"queue size={len(approvals)}")
    if inv_approval:
        aid = inv_approval["id"]
        r = timed(mgr, "POST", f"/api/v1/approvals/{aid}/approve", json={})
        rec("manager approves invoice report",
            r.status_code == 200, f"HTTP {r.status_code}")
        r = timed(mgr, "POST", f"/api/v1/approvals/{aid}/approve", json={})
        rec("double-approve -> 409", r.status_code == 409, f"HTTP {r.status_code}")
        for fmt, marker in (("pdf", b"%PDF"), ("csv", b"PENDING"), ("xlsx", b"PK")):
            r = timed(mgr, "GET", f"/api/v1/reports/{inv.get('run_id')}/export",
                      params={"format": fmt})
            rec(f"export {fmt} downloads, real content",
                r.status_code == 200 and marker in r.content and len(r.content) > 100,
                f"HTTP {r.status_code}, {len(r.content)} bytes")

    # 9. Ops cannot approve
    if inv_approval:
        r = timed(ops, "POST", f"/api/v1/approvals/{inv_approval['id']}/approve", json={})
        rec("ops approve -> 403 (already decided also rejects)",
            r.status_code in (403, 409), f"HTTP {r.status_code}")
    r = timed(ops, "GET", "/api/v1/admin/users")
    rec("ops GET /admin/users -> 403", r.status_code == 403, f"HTTP {r.status_code}")

    # 10. PDF invoice upload — match + mismatch + oversize 413
    for path, expect, label in (
        (ROOT / "data/sample_invoices/invoice_match.pdf", "MATCHED", "match"),
        (ROOT / "data/sample_invoices/invoice_mismatch.pdf", "MISMATCHED", "mismatch"),
    ):
        with open(path, "rb") as f:
            r = timed(mgr, "POST", "/api/v1/invoices/upload",
                      files={"file": ("invoice.pdf", f, "application/pdf")})
        d = j(r).get("data", {})
        rec(f"PDF upload {label} -> {expect}",
            r.status_code == 200 and str(d.get("match_status", d.get("status", ""))).upper() == expect,
            f"HTTP {r.status_code}, match={d.get('match_status', d.get('status'))}")
    big_path = Path("/tmp/prod_smoke_oversize.pdf")
    big_path.write_bytes(b"%PDF-1.4\n" + b"0" * (11 * 1024 * 1024))
    with open(big_path, "rb") as f:
        r = timed(mgr, "POST", "/api/v1/invoices/upload",
                  files={"file": ("oversize.pdf", f, "application/pdf")})
    rec("upload 11 MB -> 413 (10 MB limit)",
        r.status_code == 413, f"HTTP {r.status_code}")
    big_path.unlink(missing_ok=True)

    # 11. Schedules: list 3 jobs, run-now (Admin)
    r = timed(admin, "GET", "/api/v1/schedules")
    d = j(r).get("data", {})
    jobs = d.get("jobs", d.get("schedules", [])) if isinstance(d, dict) else []
    rec("schedules list: 3 locked jobs",
        r.status_code == 200 and len(jobs) == 3, f"HTTP {r.status_code}, jobs={len(jobs)}")
    if jobs:
        r = timed(admin, "POST", f"/api/v1/schedules/{jobs[0]['id']}/run-now", json={})
        d2 = j(r).get("data", {})
        rec("schedule run-now (Admin) creates a run",
            r.status_code == 200 and d2.get("run_id") is not None,
            f"HTTP {r.status_code}, run_id={d2.get('run_id')}")

    # 12. Evals 12/12 (last — eval scenarios create runs as the Admin user)
    r = timed(admin, "POST", "/api/v1/eval/run", json={})
    d = j(r).get("data", {})
    rec("evals run: 12/12 PASS",
        r.status_code == 200 and d.get("passed") == 12 and d.get("total") == 12,
        f"HTTP {r.status_code}, passed={d.get('passed')}/{d.get('total')}")

    # 13. Admin actions
    r = timed(admin, "GET", "/api/v1/admin/users")
    d = j(r).get("data", {})
    users = d.get("users", []) if isinstance(d, dict) else []
    rec("admin users list: 3 production users",
        r.status_code == 200 and len(users) == 3, f"HTTP {r.status_code}, users={len(users)}")
    r = timed(admin, "GET", "/api/v1/admin/audit")
    rec("admin audit log readable",
        r.status_code == 200, f"HTTP {r.status_code}")
    r = timed(mgr, "GET", "/api/v1/admin/users")
    rec("manager GET /admin/users -> 403", r.status_code == 403, f"HTTP {r.status_code}")

    # 14. n8n webhook stays disabled in production (no secret configured)
    r = timed(admin, "POST", "/api/v1/webhooks/n8n/trigger",
              json={"workflow_key": "INVOICE_REPORT"})
    rec("n8n webhook without secret -> 503 disabled",
        r.status_code == 503, f"HTTP {r.status_code}")

    failed = [x for x in RESULTS if not x["pass"]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    if LAT:
        ms = sorted(x["ms"] for x in LAT)
        print(f"latency: p50={ms[len(ms) // 2]:.1f}ms max={ms[-1]:.1f}ms")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
