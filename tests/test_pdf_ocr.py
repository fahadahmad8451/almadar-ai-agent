"""PDF invoice upload + PO match tests — Sprint 3 LIVE.

Covers POST /invoices/upload with synthetic PDFs built from the
seeded PO-2026-2001 invoice: a matching invoice (MATCHED, approval
to record as PENDING), a wrong-amount invoice (MISMATCHED, approval
to record as DISPUTED), approval execution recording the invoice in
ERP, and the rejection paths (non-PDF, empty file, unsigned-in, and
an image-only PDF with no text layer).
"""
import fitz

from app.db.session import SessionLocal
from app.services.evals import _base_invoice_fields, _synthetic_invoice_pdf
from tests.conftest import login_as

MANAGER = ("manager@almadar.local", "Manager123!")


def _match_pdf_bytes() -> bytes:
    session = SessionLocal()
    try:
        fields = _base_invoice_fields(session)
    finally:
        session.close()
    return _synthetic_invoice_pdf(fields)


def _mismatch_pdf_bytes() -> bytes:
    session = SessionLocal()
    try:
        fields = _base_invoice_fields(session)
    finally:
        session.close()
    fields["amount"] = 99999.99
    return _synthetic_invoice_pdf(fields)


def _cleanup_run(db, run_id: int, invoice_no: str | None = None):
    from app.db import models

    steps = db.query(models.WorkflowStep).filter(
        models.WorkflowStep.run_id == run_id
    ).all()
    step_ids = [s.id for s in steps]
    if step_ids:
        db.query(models.ToolCall).filter(
            models.ToolCall.step_id.in_(step_ids)
        ).delete(synchronize_session=False)
    db.query(models.WorkflowStep).filter(
        models.WorkflowStep.run_id == run_id
    ).delete(synchronize_session=False)
    db.query(models.Approval).filter(
        models.Approval.run_id == run_id
    ).delete(synchronize_session=False)
    db.query(models.WorkflowRun).filter(
        models.WorkflowRun.id == run_id
    ).delete(synchronize_session=False)
    if invoice_no:
        db.query(models.ErpInvoice).filter(
            models.ErpInvoice.invoice_no == invoice_no
        ).delete(synchronize_session=False)
    db.commit()


def test_upload_matching_invoice_creates_pending_approval(client, db):
    login_as(client, *MANAGER)
    files = {"file": ("invoice_match.pdf", _match_pdf_bytes(), "application/pdf")}
    r = client.post("/api/v1/invoices/upload", files=files)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    try:
        assert data["match_status"] == "MATCHED"
        assert data["mismatches"] == []
        assert data["method"] == "pymupdf_text"
        assert data["fields"]["invoice_no"] == "INV-2026-1999"
        assert data["fields"]["amount_sar"] == 50580.46
        assert data["fields"]["vat_sar"] == 7587.07
        assert data["approval_id"] is not None
        assert data["run_status"] == "AWAITING_APPROVAL"
        # The queued approval records the invoice as PENDING.
        r = client.get(f"/api/v1/approvals/{data['approval_id']}")
        assert r.status_code == 200
        action = r.json()["data"]["approval"]["diff"]["actions"][0]
        assert action["type"] == "record_invoice"
        assert action["status"] == "PENDING"
        assert action["invoice_no"] == "INV-2026-1999"
    finally:
        _cleanup_run(db, data["run_id"])


def test_upload_mismatched_invoice_flags_disputed(client, db):
    login_as(client, *MANAGER)
    files = {
        "file": ("invoice_mismatch.pdf", _mismatch_pdf_bytes(), "application/pdf")
    }
    r = client.post("/api/v1/invoices/upload", files=files)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    try:
        assert data["match_status"] == "MISMATCHED"
        mismatch_fields = {m["field"] for m in data["mismatches"]}
        assert "amount_sar" in mismatch_fields
        assert data["approval_id"] is not None
        r = client.get(f"/api/v1/approvals/{data['approval_id']}")
        action = r.json()["data"]["approval"]["diff"]["actions"][0]
        assert action["type"] == "record_invoice"
        assert action["status"] == "DISPUTED"
    finally:
        _cleanup_run(db, data["run_id"])


def test_approve_match_records_invoice_in_erp(client, db):
    from app.db import models

    login_as(client, *MANAGER)
    files = {"file": ("invoice_match.pdf", _match_pdf_bytes(), "application/pdf")}
    r = client.post("/api/v1/invoices/upload", files=files)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    try:
        approval_id = data["approval_id"]
        r = client.post(f"/api/v1/approvals/{approval_id}/approve")
        assert r.status_code == 200, r.text
        assert r.json()["data"]["run_status"] == "COMPLETED"
        invoice = (
            db.query(models.ErpInvoice)
            .filter(models.ErpInvoice.invoice_no == "INV-2026-1999")
            .first()
        )
        assert invoice is not None
        assert invoice.status == "PENDING"
        assert round(invoice.amount_sar, 2) == 50580.46
        assert round(invoice.vat_sar, 2) == 7587.07
    finally:
        _cleanup_run(db, data["run_id"], invoice_no="INV-2026-1999")


def test_upload_rejects_non_pdf(client):
    login_as(client, *MANAGER)
    files = {"file": ("notes.txt", b"not a pdf", "text/plain")}
    r = client.post("/api/v1/invoices/upload", files=files)
    assert r.status_code == 400


def test_upload_rejects_empty_file(client):
    login_as(client, *MANAGER)
    files = {"file": ("empty.pdf", b"", "application/pdf")}
    r = client.post("/api/v1/invoices/upload", files=files)
    assert r.status_code == 400


def test_upload_requires_sign_in(client):
    files = {"file": ("invoice_match.pdf", _match_pdf_bytes(), "application/pdf")}
    r = client.post("/api/v1/invoices/upload", files=files)
    assert r.status_code == 401


def test_upload_image_only_pdf_fails_honestly(client, db):
    """A PDF with only a drawn rectangle (no text layer) has nothing
    to extract — the service reports EXTRACTION_FAILED, it never
    fakes fields. Scanned-image OCR is PC-only (see docs/SPRINT3.md)."""
    doc = fitz.open()
    page = doc.new_page()
    page.draw_rect(fitz.Rect(10, 10, 200, 100), color=(1, 0, 0), fill=(1, 0, 0))
    pdf_bytes = doc.tobytes()
    login_as(client, *MANAGER)
    files = {"file": ("scanned.pdf", pdf_bytes, "application/pdf")}
    r = client.post("/api/v1/invoices/upload", files=files)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    try:
        assert data["match_status"] == "EXTRACTION_FAILED"
        assert data["approval_id"] is None
        assert data["run_status"] == "FAILED"
    finally:
        _cleanup_run(db, data["run_id"])


def test_attach_pdf_on_workflow_uses_same_pipeline(client, db):
    login_as(client, *MANAGER)
    files = {"file": ("invoice_match.pdf", _match_pdf_bytes(), "application/pdf")}
    r = client.post("/api/v1/workflows/INVOICE_REPORT/attach-pdf", files=files)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    try:
        assert data["match_status"] == "MATCHED"
        assert data["approval_id"] is not None
    finally:
        _cleanup_run(db, data["run_id"])
