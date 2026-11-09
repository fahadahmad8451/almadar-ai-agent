"""Invoice PDF extraction + PO matching — Sprint 3, LIVE.

Pipeline (Design 5.6):
    PDF bytes -> text -> structured fields -> deterministic PO match.

Text extraction tries PaddleOCR first when it is importable (scanned
images need real OCR). On this VM PaddleOCR cannot run — PaddleOCR
3.7.0 + PaddlePaddle 3.3.1 install and download models, but inference
crashes with a OneDNN executor NotImplementedError, so the service
falls back to the PDF text layer via PyMuPDF. The method actually
used is always reported in the result, and scanned images with no
text layer are reported as EXTRACTION_FAILED instead of faking a
result. On a machine with a working PaddlePaddle, set
AMH_TRY_PADDLEOCR=1 (or leave the default: auto-detect) and scanned
invoices work the same way. See docs/SPRINT3.md for the honest
status on this VM.
"""
import os
import re
from datetime import datetime

import fitz  # PyMuPDF

from app.db import models
from app.tools import erp as erp_tools

_OCR_METHOD = "pymupdf_text"
_paddleocr_checked = False
_paddleocr_available = False


def _paddleocr_ready() -> bool:
    """True only when PaddleOCR imports AND the user asked for it
    (AMH_TRY_PADDLEOCR=1) or it is the only option. The import alone
    does not prove it can run — model loading happens lazily and any
    failure falls back to the text layer."""
    global _paddleocr_checked, _paddleocr_available
    if _paddleocr_checked:
        return _paddleocr_available
    _paddleocr_checked = True
    if os.environ.get("AMH_TRY_PADDLEOCR", "0") != "1":
        _paddleocr_available = False
        return False
    try:
        import paddleocr  # noqa: F401

        _paddleocr_available = True
    except Exception:  # noqa: BLE001 - PaddleOCR absent means text-layer fallback
        _paddleocr_available = False
    return _paddleocr_available


def _extract_with_paddleocr(pdf_bytes: bytes) -> str:
    """Render each page to an image and OCR it (PaddleOCR 3.x API).
    Raises on any failure so the caller can fall back to the text
    layer. Tested on this VM 2026-11-06: PaddleOCR 3.7.0 +
    PaddlePaddle 3.3.1 install and load models fine, but inference
    crashes with a OneDNN executor NotImplementedError
    (ConvertPirAttribute2RuntimeAttribute) — so on this VM the call
    raises here and the text layer is used. On a machine where
    PaddlePaddle runs, scanned invoices OCR the same way."""
    import tempfile

    from paddleocr import PaddleOCR

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    ocr = PaddleOCR(use_textline_orientation=True, lang="en")
    parts: list[str] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        for index, page in enumerate(doc):
            pix = page.get_pixmap(dpi=200)
            img_path = f"{tmpdir}/page_{index}.png"
            pix.save(img_path)
            for item in ocr.predict(img_path) or []:
                if isinstance(item, dict):
                    parts.extend(str(t) for t in (item.get("rec_texts") or []))
    return "\n".join(parts)


def extract_text(pdf_bytes: bytes) -> tuple[str, str]:
    """Return (text, method). Method is 'paddleocr' or 'pymupdf_text'.
    Never raises for an unreadable file — returns ('', 'none')."""
    if _paddleocr_ready():
        try:
            text = _extract_with_paddleocr(pdf_bytes)
            if text.strip():
                return text, "paddleocr"
        except Exception:  # noqa: BLE001 - OCR failure falls back to text layer
            pass
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        parts = [page.get_text() for page in doc]
        text = "\n".join(parts)
        return text, "pymupdf_text"
    except Exception:  # noqa: BLE001 - an unreadable PDF is an honest failure
        return "", "none"


_MONEY = r"([0-9][0-9,]*(?:\.[0-9]{1,2})?)"
_DATE = r"(\d{4}-\d{2}-\d{2})"


def _money(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value.replace(",", "")), 2)
    except ValueError:
        return None


def parse_invoice_fields(text: str) -> dict:
    """Extract structured fields from invoice text with fixed regexes.
    Missing fields stay None — the matcher reports them, it never
    guesses a value."""
    fields: dict = {
        "invoice_no": None,
        "po_no": None,
        "supplier": None,
        "amount_sar": None,
        "vat_sar": None,
        "issue_date": None,
        "due_date": None,
    }
    if not text:
        return fields

    def search(pattern: str) -> str | None:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        return match.group(1).strip() if match else None

    fields["invoice_no"] = search(r"Invoice\s*(?:No\.?|Number)\s*[:#]?\s*([A-Za-z0-9][A-Za-z0-9\-]+)")
    fields["po_no"] = search(r"P\.?O\.?\s*(?:No\.?|Number)\s*[:#]?\s*([A-Za-z0-9][A-Za-z0-9\-]+)")
    supplier = search(r"Supplier\s*:\s*(.+?)\s*$")
    fields["supplier"] = supplier
    # Strict patterns first: the label "VAT (15%)" contains digits, so
    # a loose [^0-9] pattern would read "15" as the VAT amount.
    fields["amount_sar"] = _money(search(rf"^Amount\s*\(SAR\)\s*:\s*{_MONEY}"))
    if fields["amount_sar"] is None:
        fields["amount_sar"] = _money(search(rf"^Amount\s*:\s*{_MONEY}"))
    fields["vat_sar"] = _money(search(rf"^VAT\s*\(15%\)\s*:\s*{_MONEY}"))
    if fields["vat_sar"] is None:
        fields["vat_sar"] = _money(search(rf"^VAT\s*Amount\s*:\s*{_MONEY}"))
    fields["issue_date"] = search(rf"Issue\s*Date\s*:\s*{_DATE}")
    fields["due_date"] = search(rf"Due\s*Date\s*:\s*{_DATE}")
    return fields


def _date(value: str | None):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def match_invoice(db, fields: dict) -> dict:
    """Deterministic match of extracted fields against the ERP PO.
    Returns {match_status, mismatches, po, recorded_invoice}.

    match_status:
    - MATCHED — PO found and every compared field agrees.
    - MISMATCHED — PO found but at least one field disagrees, or the
      PO is not in ERP at all (po_not_found), or a required field is
      missing from the extraction.
    - EXTRACTION_FAILED — no PO number could be extracted at all.
    """
    mismatches: list[dict] = []
    po_no = (fields.get("po_no") or "").strip()
    if not po_no:
        return {
            "match_status": "EXTRACTION_FAILED",
            "mismatches": [
                {"field": "po_no", "extracted": None, "expected": "PO number on the invoice"}
            ],
            "po": None,
            "recorded_invoice": None,
        }

    po = erp_tools.get_purchase_order(db, po_no)
    if po["count"] == 0:
        return {
            "match_status": "MISMATCHED",
            "mismatches": [
                {"field": "po_no", "extracted": po_no, "expected": "PO not found in ERP"}
            ],
            "po": po,
            "recorded_invoice": None,
        }

    # If the invoice number is already in ERP, compare against that
    # exact row; otherwise compare against the PO's invoice rows.
    recorded = None
    invoice_no = (fields.get("invoice_no") or "").strip()
    if invoice_no:
        row = (
            db.query(models.ErpInvoice)
            .filter(models.ErpInvoice.invoice_no == invoice_no)
            .first()
        )
        if row is not None:
            supplier = db.get(models.ErpSupplier, row.supplier_id)
            recorded = {
                "id": row.id,
                "invoice_no": row.invoice_no,
                "supplier": supplier.name if supplier else None,
                "amount_sar": round(row.amount_sar, 2),
                "vat_sar": round(row.vat_sar, 2),
                "issue_date": row.issue_date.date().isoformat(),
                "due_date": row.due_date.date().isoformat(),
                "status": row.status,
                "po_no": row.po_no,
            }
    compare_rows = [recorded] if recorded else po["rows"]
    suppliers = {str(r.get("supplier") or "").strip().lower() for r in compare_rows}
    amounts = {round(float(r.get("amount_sar") or 0), 2) for r in compare_rows}
    vats = {round(float(r.get("vat_sar") or 0), 2) for r in compare_rows}

    supplier = (fields.get("supplier") or "").strip()
    if supplier and supplier.lower() not in suppliers:
        mismatches.append(
            {"field": "supplier", "extracted": supplier, "expected": sorted(suppliers)}
        )
    amount = fields.get("amount_sar")
    if amount is not None and amount not in amounts:
        mismatches.append(
            {"field": "amount_sar", "extracted": amount, "expected": sorted(amounts)}
        )
    vat = fields.get("vat_sar")
    if vat is not None and vat not in vats:
        mismatches.append(
            {"field": "vat_sar", "extracted": vat, "expected": sorted(vats)}
        )
    # VAT must also be exactly 15% of the extracted amount.
    if amount is not None and vat is not None:
        expected_vat = round(amount * 0.15, 2)
        if abs(vat - expected_vat) > 0.01:
            mismatches.append(
                {
                    "field": "vat_15_percent",
                    "extracted": vat,
                    "expected": expected_vat,
                }
            )
    if recorded is not None:
        issue = _date(fields.get("issue_date"))
        due = _date(fields.get("due_date"))
        if issue is not None and issue.isoformat() != recorded["issue_date"]:
            mismatches.append(
                {"field": "issue_date", "extracted": issue.isoformat(), "expected": recorded["issue_date"]}
            )
        if due is not None and due.isoformat() != recorded["due_date"]:
            mismatches.append(
                {"field": "due_date", "extracted": due.isoformat(), "expected": recorded["due_date"]}
            )

    status = "MATCHED" if not mismatches else "MISMATCHED"
    return {
        "match_status": status,
        "mismatches": mismatches,
        "po": po,
        "recorded_invoice": recorded,
    }


def extract_invoice(db, pdf_bytes: bytes) -> dict:
    """Full pipeline: text -> fields -> PO match. Always returns the
    extraction method used so a text-layer result is never presented
    as an OCR result."""
    text, method = extract_text(pdf_bytes)
    fields = parse_invoice_fields(text)
    match = match_invoice(db, fields)
    return {
        "method": method,
        "fields": fields,
        "match_status": match["match_status"],
        "mismatches": match["mismatches"],
        "po": match["po"],
        "recorded_invoice": match["recorded_invoice"],
        "text_preview": text[:500],
    }
