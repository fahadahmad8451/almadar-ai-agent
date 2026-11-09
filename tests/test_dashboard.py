"""Dashboard summary tests — Production (v0.8.0).

GET /dashboard/summary is the read-only endpoint the Dashboard home
uses (it replaced the v0.7.0 Dashboard's two instruct calls). The
figures come straight from the database — no agent run, no instruct
budget. Expected values are computed from the same tables inside the
test, so the assertions hold even when other tests add rows.
"""
from sqlalchemy import func

from app.db import models
from tests.conftest import login_as


def _expected(db):
    pending = (
        db.query(
            func.count(models.ErpInvoice.id),
            func.coalesce(func.sum(models.ErpInvoice.amount_sar), 0),
            func.coalesce(func.sum(models.ErpInvoice.vat_sar), 0),
        )
        .filter(models.ErpInvoice.status == "PENDING")
        .one()
    )
    overdue = (
        db.query(func.count(func.distinct(models.ErpInvoice.supplier_id)),
                func.coalesce(func.sum(models.ErpInvoice.amount_sar), 0))
        .filter(models.ErpInvoice.status == "OVERDUE")
        .one()
    )
    return pending, overdue


def test_dashboard_summary_matches_database(client, db, make_user):
    user = make_user("OPERATIONS_MANAGER")
    login_as(client, user.email, "Test123!")
    r = client.get("/api/v1/dashboard/summary")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    pending, overdue = _expected(db)
    assert data["pending_invoices"]["count"] == int(pending[0])
    assert data["pending_invoices"]["total_sar"] == round(float(pending[1]), 2)
    assert data["pending_invoices"]["vat_sar"] == round(float(pending[2]), 2)
    assert data["overdue_suppliers"]["count"] == int(overdue[0])
    assert data["overdue_suppliers"]["total_sar"] == round(float(overdue[1]), 2)
    assert isinstance(data["overdue_suppliers"]["names"], list)
    assert "pending_approvals" in data
    assert "evals" in data
    assert "recent_runs" in data
    assert data["generated_at"]


def test_dashboard_summary_seed_values(client, db):
    # On the seeded database the figures are the known Testing values:
    # 12 pending invoices totalling 581,100.19 SAR (VAT 87,165.03)
    # and 3 overdue suppliers totalling 164,941.98 SAR. Other tests
    # may add rows first, so assert at-least (exact on a fresh seed).
    login_as(client, "manager@almadar.local", "Manager123!")
    r = client.get("/api/v1/dashboard/summary")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["pending_invoices"]["count"] >= 12
    assert data["pending_invoices"]["total_sar"] >= 581100.19
    assert data["overdue_suppliers"]["count"] >= 3
    assert data["overdue_suppliers"]["total_sar"] >= 164941.98


def test_dashboard_summary_requires_auth(client):
    r = client.get("/api/v1/dashboard/summary")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


def test_dashboard_summary_officer_can_read(client, db, make_user):
    # Read-only: an Operations Officer may see the dashboard too
    # (only their own runs/approvals inside it).
    user = make_user("OPERATIONS_OFFICER")
    login_as(client, user.email, "Test123!")
    r = client.get("/api/v1/dashboard/summary")
    assert r.status_code == 200, r.text
    assert "pending_invoices" in r.json()["data"]
