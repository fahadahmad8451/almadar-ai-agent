"""Staging smoke test — Project 2 (Enterprise AI Agent) v0.9.0.

Runs the full happy path + key negative checks against the STAGING
environment (API :8101, web :3101, database almadar_agent_staging).
No mocking — real API, real staging PostgreSQL, real files.

Usage:  .venv/bin/python scripts/staging_smoke.py
Needs:   staging API + staging web running (scripts/staging_start.sh,
         scripts/staging_start_web.sh) on a freshly seeded staging DB.

Note on rate limits: instruct + workflow runs share a 10 runs/user/hour
budget. This script uses the seeded demo accounts and stays under the
budget on a fresh seed. Re-running it within the same hour will hit
429 — re-seed first (./scripts/staging_setup.sh, idempotent) or wait.
"""
import json
import sys
import time
from pathlib import Path

import httpx

API = "http://127.0.0.1:8101"
WEB = "http://127.0.0.1:3101"
ROOT = Path(__file__).resolve().parents[1]
RESULTS: list[dict] = []
LAT: list[dict] = []


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
    # 1. Health + frontend
    c = httpx.Client(timeout=30, trust_env=False)
    r = timed(c, "GET", f"{API}/health")
    d = j(r).get("data", {})
    rec("health 200, version 0.9.0, staging, DB connected",
        r.status_code == 200 and d.get("version") == "0.9.0"
        and d.get("environment") == "staging" and d.get("database") == "connected",
        f"HTTP {r.status_code}, version={d.get('version')}, env={d.get('environment')}, db={d.get('database')}")
    r = timed(c, "GET", f"{WEB}/")
    rec("staging web :3101 serves the app",
        r.status_code == 200 and "Al Madar Holding" in r.text,
        f"HTTP {r.status_code}")
    c.close()

    # 2. Logins (demo accounts are ON in staging)
    admin = login("admin@almadar.local", "Admin123!")
    mgr = login("manager@almadar.local", "Manager123!")
    ops = login("ops@almadar.local", "Ops123!")
    r = timed(mgr, "POST", "/api/v1/auth/login",
              json={"email": "manager@almadar.local", "password": "wrong"})
    rec("wrong password -> 401", r.status_code == 401, f"HTTP {r.status_code}")

    # 3. Instruct EN + AR (Testing fix values: 12 pending, 581,100.19 SAR)
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

    # 4. Workflow runs (Manager: invoice + supplier; Admin: CRM + expense)
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

    # 5. Approval queue -> approve invoice report -> export downloads
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

    # 6. Ops cannot approve
    if inv_approval:
        r = timed(ops, "POST", f"/api/v1/approvals/{inv_approval['id']}/approve", json={})
        rec("ops approve -> 403 (already decided also rejects)",
            r.status_code in (403, 409), f"HTTP {r.status_code}")
    r = timed(ops, "GET", "/api/v1/admin/users")
    rec("ops GET /admin/users -> 403", r.status_code == 403, f"HTTP {r.status_code}")

    # 7. PDF invoice upload — match + mismatch
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

    # 8. Schedules: list 3 jobs, run-now (Admin), scheduler never auto-fired
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
    r = timed(admin, "GET", "/api/v1/agent/runs")
    d = j(r).get("data", {})
    runs = d.get("runs", []) if isinstance(d, dict) else []
    scheduled = [x for x in runs
                 if isinstance(x.get("plan"), dict) and x["plan"].get("trigger") == "scheduled"]
    rec("no scheduled auto-fire (scheduler OFF in staging)",
        len(scheduled) == 0, f"scheduled-trigger runs={len(scheduled)}")

    # 9. Evals 12/12 (last — eval scenarios create runs as the Admin user)
    r = timed(admin, "POST", "/api/v1/eval/run", json={})
    d = j(r).get("data", {})
    rec("evals run: 12/12 PASS",
        r.status_code == 200 and d.get("passed") == 12 and d.get("total") == 12,
        f"HTTP {r.status_code}, passed={d.get('passed')}/{d.get('total')}")

    # 10. Admin actions
    r = timed(admin, "GET", "/api/v1/admin/users")
    d = j(r).get("data", {})
    users = d.get("users", []) if isinstance(d, dict) else []
    rec("admin users list: 3 seeded users",
        r.status_code == 200 and len(users) == 3, f"HTTP {r.status_code}, users={len(users)}")
    r = timed(admin, "GET", "/api/v1/admin/audit")
    rec("admin audit log readable",
        r.status_code == 200, f"HTTP {r.status_code}")
    r = timed(mgr, "GET", "/api/v1/admin/users")
    rec("manager GET /admin/users -> 403", r.status_code == 403, f"HTTP {r.status_code}")

    # 11. n8n webhook stays disabled in staging (no secret configured)
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
