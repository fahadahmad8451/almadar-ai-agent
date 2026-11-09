"""Invoice upload endpoint — Sprint 3, LIVE.

POST /invoices/upload (multipart, PDF only, 10 MB limit):
extracts the invoice fields, matches them against the ERP purchase
order, and queues a match/mismatch report for a manager's approval.
Nothing is written to ERP by the upload itself — the approval
executes the record_invoice write tool (Design 5.6).
"""
from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.api.v1._helpers import fail, ok
from app.core.config import settings
from app.core.security import get_current_user
from app.db import models
from app.db.session import get_db
from app.services import invoice_upload as upload_service

router = APIRouter()

MAX_BYTES = 10 * 1024 * 1024


@router.post("/upload")
async def upload_invoice(
    file: UploadFile = File(...),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    filename = (file.filename or "invoice.pdf").strip() or "invoice.pdf"
    if not filename.lower().endswith(".pdf"):
        return fail(400, "invalid_file", "Only PDF files are accepted.")
    pdf_bytes = await file.read()
    if len(pdf_bytes) > MAX_BYTES:
        return fail(
            413,
            "file_too_large",
            f"PDF is {len(pdf_bytes) / 1024 / 1024:.1f} MB — the limit is {settings.max_upload_mb} MB.",
        )
    if len(pdf_bytes) == 0:
        return fail(400, "invalid_file", "The uploaded file is empty.")
    try:
        result = upload_service.process_invoice_upload(db, user, pdf_bytes, filename)
    except ValueError as exc:
        return fail(400, "invalid_params", str(exc))
    return ok(result)
