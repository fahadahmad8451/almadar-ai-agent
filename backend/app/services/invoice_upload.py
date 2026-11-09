"""Invoice PDF upload processing — Sprint 3, LIVE.

One shared pipeline for POST /invoices/upload and
POST /workflows/{key}/attach-pdf (Design 5.6):
    PDF -> extract fields -> PO match -> approval queue.

Nothing is recorded in ERP by the upload itself. A matched invoice
creates an approval to record it as PENDING; a mismatched one
creates an approval to record it as DISPUTED. A manager approves
the approval — only then does the record_invoice write tool run.
An unreadable PDF, a missing PO number, or any missing required
field means EXTRACTION_FAILED: no approval, the run is FAILED, and
the response says exactly what is missing.
"""
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.agents.supervisor import _record_step
from app.core.config import settings
from app.core.security import audit
from app.db import models
from app.services import approval as approval_service
from app.tools import ocr as ocr_tools

REQUIRED_FIELDS = ("invoice_no", "supplier", "amount_sar", "vat_sar", "issue_date", "due_date")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def save_upload(pdf_bytes: bytes, filename: str) -> Path:
    """Store the uploaded PDF under data/uploads/. Returns the path."""
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename or "invoice.pdf").name
    path = upload_dir / f"{uuid.uuid4().hex}_{safe_name}"
    path.write_bytes(pdf_bytes)
    return path


def process_invoice_upload(
    db: Session,
    user: models.User,
    pdf_bytes: bytes,
    filename: str,
    workflow_key: str = "INVOICE_REPORT",
) -> dict:
    """Run the full upload pipeline and return the public result."""
    workflow = (
        db.query(models.Workflow).filter(models.Workflow.key == workflow_key).first()
    )
    if workflow is None:
        raise ValueError(f"Workflow {workflow_key} not found.")
    file_path = save_upload(pdf_bytes, filename)

    run = models.WorkflowRun(
        workflow_id=workflow.id,
        user_id=user.id,
        instruction=f"Invoice PDF upload: {filename}",
        language="en",
        status="RUNNING",
        confidence=None,
        plan={"trigger": "upload", "file_path": str(file_path)},
        started_at=_now(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    started = time.monotonic()
    result = ocr_tools.extract_invoice(db, pdf_bytes)
    fields = result["fields"]
    match_status = result["match_status"]
    missing = [f for f in REQUIRED_FIELDS if fields.get(f) is None]
    if match_status != "EXTRACTION_FAILED" and missing:
        match_status = "EXTRACTION_FAILED"
        result["mismatches"] = [
            {"field": f, "extracted": None, "expected": "field missing on the invoice"}
            for f in missing
        ]
    _record_step(
        db, run.id, "invoice_agent", 0, "extract_and_match",
        {"file": filename, "method": result["method"]},
        {
            "fields": fields,
            "match_status": match_status,
            "mismatches": result["mismatches"],
        },
        "success" if match_status != "EXTRACTION_FAILED" else "failed",
        int((time.monotonic() - started) * 1000),
    )

    approval_id = None
    note = ""
    if match_status == "EXTRACTION_FAILED":
        run.status = "FAILED"
        note = "Extraction failed — manual entry required."
    elif result.get("recorded_invoice") is not None:
        run.status = "COMPLETED"
        note = (
            f"Invoice {fields['invoice_no']} is already recorded in ERP "
            f"({result['recorded_invoice']['status']}). No approval needed."
        )
    else:
        po_rows = (result.get("po") or {}).get("rows") or []
        supplier_id = po_rows[0].get("supplier_id") if po_rows else None
        record_status = "PENDING" if match_status == "MATCHED" else "DISPUTED"
        action = {
            "type": "record_invoice",
            "invoice_no": fields["invoice_no"],
            "supplier_id": supplier_id,
            "amount_sar": fields["amount_sar"],
            "vat_sar": fields["vat_sar"],
            "issue_date": fields["issue_date"],
            "due_date": fields["due_date"],
            "status": record_status,
            "po_no": fields["po_no"],
        }
        summary = (
            f"Record invoice {fields['invoice_no']} "
            f"({fields['supplier']}, {fields['amount_sar']:,.2f} SAR) as {record_status}."
        )
        if match_status == "MISMATCHED":
            summary += f" Mismatches: {len(result['mismatches'])} field(s) differ from the PO."
        approvals = approval_service.create_approvals_for_run(
            db,
            run,
            user,
            {"approval_items": [{"action_summary": summary, "diff": {"actions": [action]}}]},
        )
        approval_id = approvals[0].id if approvals else None
        _record_step(
            db, run.id, "approval_agent", 1, "create_approvals",
            {"approval_ids": [approval_id] if approval_id else []},
            {"count": len(approvals)},
            "success", 0,
        )
        run.status = "AWAITING_APPROVAL"
        note = (
            "Match report queued for approval."
            if match_status == "MATCHED"
            else "Mismatch report queued for approval — review before recording."
        )

    run.finished_at = _now()
    db.commit()
    audit(
        db,
        user_id=user.id,
        action="INVOICE_UPLOAD",
        resource=f"invoices/upload",
        result=run.status,
        details={
            "run_id": run.id,
            "file": filename,
            "method": result["method"],
            "match_status": match_status,
            "approval_id": approval_id,
        },
    )
    return {
        "upload_id": run.id,
        "run_id": run.id,
        "file_name": filename,
        "file_path": str(file_path),
        "method": result["method"],
        "fields": fields,
        "match_status": match_status,
        "mismatches": result["mismatches"],
        "recorded_invoice": result.get("recorded_invoice"),
        "approval_id": approval_id,
        "run_status": run.status,
        "note": note,
    }
