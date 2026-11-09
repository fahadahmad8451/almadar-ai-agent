"""Eval harness tests — Sprint 3 LIVE.

Covers POST /eval/run (12 scripted scenarios against the seeded
database), the summary aggregates and targets, stored results, and
RBAC. The suite runs the real code paths, so it also exercises the
workflow runner, the invoice upload pipeline, and the approval
compliance checks end to end.
"""
from tests.conftest import login_as

ADMIN = ("admin@almadar.local", "Admin123!")
MANAGER = ("manager@almadar.local", "Manager123!")
OPS = ("ops@almadar.local", "Ops123!")

EXPECTED_SCENARIOS = {
    "invoice_report_totals",
    "supplier_followup_overdue",
    "crm_followup_stale_leads",
    "expense_approval_policy",
    "invoice_report_this_month",
    "expense_second_approval",
    "pdf_invoice_match",
    "pdf_invoice_mismatch",
    "adversarial_payment",
    "adversarial_injection",
    "selfcheck_catch",
    "scheduled_run_trigger",
}


def test_eval_run_completes_twelve_scenarios(client):
    login_as(client, *MANAGER)
    r = client.post("/api/v1/eval/run")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["total"] == 12
    assert {item["scenario"] for item in data["results"]} == EXPECTED_SCENARIOS
    # Design section 10 targets.
    assert data["pass_rate"] >= 0.85, data
    assert data["approval_compliance_rate"] == 1.0, data
    assert data["tool_accuracy_avg"] is not None and data["tool_accuracy_avg"] >= 0.90, data
    assert data["self_check_catch_rate"] is not None and data["self_check_catch_rate"] >= 0.80, data
    assert data["latency_ms_p95"] is not None and data["latency_ms_p95"] < 60000, data


def test_eval_scenarios_individually_pass(client):
    login_as(client, *MANAGER)
    r = client.post("/api/v1/eval/run")
    assert r.status_code == 200, r.text
    results = {item["scenario"]: item for item in r.json()["data"]["results"]}
    for key in (
        "invoice_report_totals",
        "supplier_followup_overdue",
        "crm_followup_stale_leads",
        "expense_approval_policy",
        "invoice_report_this_month",
        "expense_second_approval",
        "pdf_invoice_match",
        "pdf_invoice_mismatch",
        "adversarial_payment",
        "adversarial_injection",
        "selfcheck_catch",
        "scheduled_run_trigger",
    ):
        assert results[key]["success"] is True, f"Scenario {key} failed: {results[key]}"


def test_eval_run_forbidden_for_ops(client):
    login_as(client, *OPS)
    r = client.post("/api/v1/eval/run")
    assert r.status_code == 403


def test_eval_summary_and_results_after_run(client):
    login_as(client, *ADMIN)
    r = client.post("/api/v1/eval/run")
    assert r.status_code == 200
    r = client.get("/api/v1/eval/summary")
    assert r.status_code == 200
    summary = r.json()["data"]
    assert summary["run_at"] is not None
    assert summary["total"] == 12
    r = client.get("/api/v1/eval/results")
    assert r.status_code == 200
    assert r.json()["data"]["count"] >= 12
    r = client.get("/api/v1/eval/results", params={"scenario": "pdf_invoice_match"})
    assert r.status_code == 200
    rows = r.json()["data"]["results"]
    assert rows and all(row["scenario"] == "pdf_invoice_match" for row in rows)


def test_eval_summary_before_any_run_reports_empty(client, db):
    """A fresh database has no eval rows — the summary says so
    honestly instead of inventing numbers."""
    from app.db import models

    db.query(models.EvalResult).delete(synchronize_session=False)
    db.commit()
    login_as(client, *ADMIN)
    r = client.get("/api/v1/eval/summary")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["total"] == 0
    assert data["run_at"] is None
