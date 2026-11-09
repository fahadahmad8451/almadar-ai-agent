"""Report export tests — Sprint 2 LIVE.

Exports are real files: a PDF that starts with %PDF, a CSV with a
real header and real rows, an XLSX that is a real spreadsheet
(magic bytes PK). Downloads are blocked (409) until the run's
approval executes, and require sign-in.
"""
from tests.conftest import login_as

MANAGER = ("manager@almadar.local", "Manager123!")


def _run_and_approve(client, make_user, key):
    """Run a workflow as a throwaway Ops user, approve it as the
    seeded manager. Returns the run data."""
    user = make_user("OPERATIONS_OFFICER")
    login_as(client, user.email, "Test123!")
    r = client.post(f"/api/v1/workflows/{key}/run", json={"params": {}})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["status"] == "AWAITING_APPROVAL"
    login_as(client, *MANAGER)
    for approval_id in data["approval_ids"]:
        r = client.post(f"/api/v1/approvals/{approval_id}/approve")
        assert r.status_code == 200, r.text
    return data


def test_export_pdf_is_a_real_pdf(client, make_user):
    data = _run_and_approve(client, make_user, "INVOICE_REPORT")
    r = client.get(f"/api/v1/reports/{data['run_id']}/export?format=pdf")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content[:4] == b"%PDF"
    assert len(r.content) > 500


def test_export_csv_has_real_header_and_rows(client, make_user):
    data = _run_and_approve(client, make_user, "INVOICE_REPORT")
    r = client.get(f"/api/v1/reports/{data['run_id']}/export?format=csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    text = r.content.decode("utf-8")
    lines = [line for line in text.splitlines() if line.strip()]
    assert lines[0] == "Pending Invoices Report"  # title row
    assert lines[1].startswith("Invoice No")  # header row
    assert "SAR" in text
    assert len(lines) > 3  # title + header + at least one data row + totals


def test_export_xlsx_is_a_real_spreadsheet(client, make_user):
    data = _run_and_approve(client, make_user, "INVOICE_REPORT")
    r = client.get(f"/api/v1/reports/{data['run_id']}/export?format=xlsx")
    assert r.status_code == 200
    assert r.content[:2] == b"PK"  # XLSX is a ZIP archive
    assert len(r.content) > 1000


def test_export_blocked_before_approval(client, make_user):
    user = make_user("OPERATIONS_OFFICER")
    login_as(client, user.email, "Test123!")
    r = client.post("/api/v1/workflows/INVOICE_REPORT/run", json={"params": {}})
    assert r.status_code == 200
    run_id = r.json()["data"]["run_id"]
    login_as(client, *MANAGER)
    r = client.get(f"/api/v1/reports/{run_id}/export?format=pdf")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "approval_required"


def test_export_requires_auth(client):
    r = client.get("/api/v1/reports/1/export?format=pdf")
    assert r.status_code == 401


def test_reports_list_shows_approved_export(client, make_user):
    data = _run_and_approve(client, make_user, "INVOICE_REPORT")
    login_as(client, *MANAGER)
    r = client.get("/api/v1/reports")
    assert r.status_code == 200
    mine = [e for e in r.json()["data"]["exports"] if e["run_id"] == data["run_id"]]
    assert mine
    assert mine[0]["format"] == "pdf"
    assert mine[0]["file_name"].endswith(".pdf")
    assert mine[0]["download_url"].endswith("format=pdf")


def test_supplier_draft_saved_after_approval(client, make_user):
    data = _run_and_approve(client, make_user, "SUPPLIER_FOLLOWUP")
    login_as(client, *MANAGER)
    r = client.get("/api/v1/drafts")
    assert r.status_code == 200
    mine = [d for d in r.json()["data"]["drafts"] if d["run_id"] == data["run_id"]]
    assert mine, "Approved supplier drafts must be saved"
    assert all(d["status"] == "APPROVED" for d in mine)
    assert mine[0]["to_email"]
    assert mine[0]["subject"]
    assert len(mine[0]["body"]) > 20
