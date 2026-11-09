"""Generate synthetic test invoice PDFs — Sprint 3.

Two PDFs, both built from the seeded PO-2026-2001 invoice so the
fields always agree with the database:
- invoice_match.pdf — a NEW invoice number (INV-2026-1999) for the
  same supplier, amount, VAT and dates as PO-2026-2001: the matcher
  must report MATCHED and queue a PENDING record approval.
- invoice_mismatch.pdf — the same invoice with a wrong amount
  (99,999.99 SAR): the matcher must flag amount, VAT and the 15%
  VAT rule as mismatches and queue a DISPUTED record approval.

Usage (from the project root):
    python scripts/generate_test_invoice.py
Output: data/sample_invoices/invoice_match.pdf,
        data/sample_invoices/invoice_mismatch.pdf
Everything is synthetic. No real supplier or financial data.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.db.session import SessionLocal
from app.db import models

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "sample_invoices"

LINES_TEMPLATE = [
    "INVOICE",
    "",
    "Invoice No: {invoice_no}",
    "Supplier: {supplier}",
    "PO Number: {po_no}",
    "Issue Date: {issue_date}",
    "Due Date: {due_date}",
    "",
    "Amount (SAR): {amount:.2f}",
    "VAT (15%): {vat:.2f}",
    "Total (SAR): {total:.2f}",
]


def draw_invoice(path: Path, fields: dict) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont("Helvetica-Bold", 20)
    y = 780
    for line in LINES_TEMPLATE:
        text = line.format(**fields)
        c.setFont("Helvetica-Bold", 20 if line == "INVOICE" else 12)
        c.drawString(72, y, text)
        y -= 28
    c.save()


def main() -> None:
    db = SessionLocal()
    try:
        inv = (
            db.query(models.ErpInvoice)
            .filter(models.ErpInvoice.po_no == "PO-2026-2001")
            .order_by(models.ErpInvoice.id)
            .first()
        )
        if inv is None:
            raise SystemExit("Seed invoice for PO-2026-2001 not found — run scripts/seed.py first.")
        supplier = db.get(models.ErpSupplier, inv.supplier_id)
        base = {
            "invoice_no": "INV-2026-1999",
            "supplier": supplier.name,
            "po_no": inv.po_no,
            "issue_date": inv.issue_date.date().isoformat(),
            "due_date": inv.due_date.date().isoformat(),
            "amount": round(inv.amount_sar, 2),
            "vat": round(inv.vat_sar, 2),
            "total": round(inv.amount_sar + inv.vat_sar, 2),
        }
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        draw_invoice(OUT_DIR / "invoice_match.pdf", base)
        mismatch = dict(base)
        mismatch["amount"] = 99999.99
        mismatch["total"] = round(99999.99 + base["vat"], 2)
        draw_invoice(OUT_DIR / "invoice_mismatch.pdf", mismatch)
        print(f"Wrote {OUT_DIR / 'invoice_match.pdf'}")
        print(f"Wrote {OUT_DIR / 'invoice_mismatch.pdf'}")
        print(f"Match invoice: {base['invoice_no']} {base['supplier']} {base['amount']:.2f} SAR + {base['vat']:.2f} VAT, PO {base['po_no']}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
