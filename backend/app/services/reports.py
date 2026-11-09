"""Report Agent — Sprint 2, LIVE.

Builds real reports from Data Agent tool results and exports real
files (PDF via ReportLab, CSV via the standard library, XLSX via
openpyxl). Every number comes from the tool results — the agent never
invents figures. The report payload is stored on the workflow run
(`run.plan["report"]`) so exports are reproducible from the approved
run, and every generated file is recorded in `report_exports`.

Exports are rendered in English (Latin script): ReportLab's built-in
fonts cannot shape Arabic text, and an Arabic PDF needs a shaped
font pipeline. Arabic summaries are delivered in the API response
and the UI; the exported files carry the same data in English.
"""
import csv
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from app.core.config import settings
from app.db import models
from app.services import expense_policy

EXPORT_FORMATS = ("pdf", "csv", "xlsx")
DEFAULT_FORMAT = {"INVOICE_REPORT": "pdf", "SUPPLIER_FOLLOWUP": "pdf", "CRM_FOLLOWUP": "csv", "EXPENSE_APPROVAL": "pdf"}

REPORT_TITLES = {
    "INVOICE_REPORT": ("Pending Invoices Report", "تقرير الفواتير المعلقة"),
    "SUPPLIER_FOLLOWUP": ("Overdue Supplier Follow-up", "متابعة الموردين المتأخرين"),
    "CRM_FOLLOWUP": ("CRM Follow-up Digest", "ملخص متابعة العملاء"),
    "EXPENSE_APPROVAL": ("Expense Claims for Approval", "مطالبات المصاريف للاعتماد"),
}


def _result_by_tool(tool_results: list[dict], name: str) -> dict:
    for item in tool_results:
        if item.get("tool") == name:
            return item.get("result") or {}
    return {"rows": [], "count": 0}


def _money(value) -> str:
    try:
        return f"{float(value or 0):,.2f}"
    except (TypeError, ValueError):
        return "0.00"


def _supplier_draft_text(supplier: dict, language: str) -> tuple[str, str]:
    """One reminder email per overdue supplier (EN or AR)."""
    name = supplier.get("name") or "Supplier"
    total = _money(supplier.get("overdue_total_sar"))
    nos = ", ".join(supplier.get("overdue_invoice_nos") or [])
    if language == "ar":
        subject = f"تذكير بفواتير متأخرة — {name}"
        body = (
            f"عزيزي {name}،\n\n"
            f"نود تذكيركم بأن لديكم فواتير متأخرة بقيمة {total} ر.س "
            f"(أرقام الفواتير: {nos}).\n"
            "يرجى ترتيب الدفع في أقرب وقت ممكن.\n\n"
            "مع الشكر،\nبنك الرياض الائتماني — إدارة العمليات"
        )
    else:
        subject = f"Overdue invoice reminder — {name}"
        body = (
            f"Dear {name},\n\n"
            f"This is a reminder that you have overdue invoices totalling "
            f"{total} SAR (invoice numbers: {nos}).\n"
            "Please arrange payment at your earliest convenience.\n\n"
            "Thank you,\nAl Madar Holding — Operations"
        )
    return subject, body


def _crm_draft_text(lead: dict, language: str) -> tuple[str, str]:
    """One follow-up message per stale lead (EN or AR)."""
    name = lead.get("name") or "Customer"
    if language == "ar":
        subject = f"متابعة — {name}"
        body = (
            f"عزيزي {name}،\n\n"
            "لم نتواصل معكم منذ فترة. هل تودون مناقشة خدماتنا المصرفية "
            "للشركات؟ يسعدنا تحديد موعد لمناقشة احتياجاتكم.\n\n"
            "مع الشكر،\nبنك الرياض الائتماني — إدارة علاقات العملاء"
        )
    else:
        subject = f"Follow-up — {name}"
        body = (
            f"Dear {name},\n\n"
            "We have not been in touch for a while. Would you like to "
            "discuss our corporate services? We would be glad to "
            "schedule a call to review your needs.\n\n"
            "Thank you,\nAl Madar Holding — Customer Relations"
        )
    return subject, body


def build_report(
    workflow_key: str,
    language: str,
    tool_results: list[dict],
    export_format: str,
    db=None,
) -> dict:
    """Build the report payload for a workflow run from its tool
    results. Returns the payload stored on the run plus the approval
    items the Approval Agent turns into approval rows.

    The payload is pure data (JSON-serialisable) — no file is written
    here; files are written only when an approval executes.
    """
    title, title_ar = REPORT_TITLES.get(workflow_key, (workflow_key, workflow_key))
    report: dict = {
        "workflow_key": workflow_key,
        "language": language,
        "title": title,
        "title_ar": title_ar,
        "columns": [],
        "rows": [],
        "totals": {},
        "notes": [],
        "drafts": [],
        "claims": [],
        "approval_items": [],
    }

    if workflow_key == "INVOICE_REPORT":
        result = _result_by_tool(tool_results, "list_invoices")
        rows = result.get("rows", [])
        report["columns"] = [
            "Invoice No", "Supplier", "Amount (SAR)", "VAT (SAR)",
            "Issue Date", "Due Date", "Status", "PO No",
        ]
        report["rows"] = [
            [
                r.get("invoice_no"), r.get("supplier"), r.get("amount_sar"),
                r.get("vat_sar"), r.get("issue_date"), r.get("due_date"),
                r.get("status"), r.get("po_no"),
            ]
            for r in rows
        ]
        report["totals"] = {
            "count": result.get("count", len(rows)),
            "total_amount_sar": result.get("total_amount_sar", 0),
            "total_vat_sar": result.get("total_vat_sar", 0),
        }
        suppliers = _result_by_tool(tool_results, "list_suppliers")
        overdue = [s for s in suppliers.get("rows", []) if s.get("overdue_invoice_count", 0) > 0]
        if overdue:
            report["notes"].append(
                f"{len(overdue)} supplier(s) have overdue invoices totalling "
                f"{sum(s.get('overdue_total_sar', 0) for s in overdue):,.2f} SAR."
            )
        report["approval_items"].append({
            "action_summary": f"Export invoice report as {export_format.upper()} "
            f"({report['totals']['count']} invoices, "
            f"{_money(report['totals']['total_amount_sar'])} SAR).",
            "diff": {"actions": [{"type": "export_report", "format": export_format}]},
        })

    elif workflow_key == "SUPPLIER_FOLLOWUP":
        result = _result_by_tool(tool_results, "list_suppliers")
        rows = result.get("rows", [])
        report["columns"] = [
            "Supplier", "Contact Email", "Overdue Invoices",
            "Overdue Total (SAR)", "Invoice Nos",
        ]
        report["rows"] = [
            [
                r.get("name"), r.get("contact_email"),
                r.get("overdue_invoice_count"), r.get("overdue_total_sar"),
                ", ".join(r.get("overdue_invoice_nos") or []),
            ]
            for r in rows
        ]
        report["totals"] = {
            "count": len(rows),
            "total_amount_sar": round(sum(r.get("overdue_total_sar", 0) for r in rows), 2),
        }
        for supplier in rows:
            email = supplier.get("contact_email")
            if not email:
                report["notes"].append(
                    f"{supplier.get('name')}: cannot draft — no email on file."
                )
                continue
            subject, body = _supplier_draft_text(supplier, language)
            draft = {"to_email": email, "subject": subject, "body": body}
            report["drafts"].append(draft)
            report["approval_items"].append({
                "action_summary": (
                    f"Save reminder email draft for {supplier.get('name')} "
                    f"({supplier.get('overdue_invoice_count')} overdue invoice(s), "
                    f"{_money(supplier.get('overdue_total_sar'))} SAR)."
                ),
                "diff": {"actions": [{"type": "save_email_draft", "draft": draft}]},
            })

    elif workflow_key == "CRM_FOLLOWUP":
        leads = _result_by_tool(tool_results, "list_leads")
        lead_rows = leads.get("rows", [])
        report["columns"] = ["Lead", "Email", "Source", "Score", "Last Activity", "Status"]
        report["rows"] = [
            [
                r.get("name"), r.get("email"), r.get("source"),
                r.get("score"), r.get("last_activity_at"), r.get("status"),
            ]
            for r in lead_rows
        ]
        report["totals"] = {"count": len(lead_rows)}
        actions = [{"type": "export_report", "format": export_format}]
        for lead in lead_rows:
            if not lead.get("email"):
                report["notes"].append(
                    f"{lead.get('name')}: included in the list but flagged "
                    "— no contact channel."
                )
                continue
            subject, body = _crm_draft_text(lead, language)
            draft = {"to_email": lead["email"], "subject": subject, "body": body}
            report["drafts"].append(draft)
            actions.append({"type": "save_email_draft", "draft": draft})
        report["approval_items"].append({
            "action_summary": (
                f"Export CRM follow-up list as {export_format.upper()} "
                f"({len(lead_rows)} stale lead(s)) and save "
                f"{len(report['drafts'])} follow-up draft(s)."
            ),
            "diff": {"actions": actions},
        })

    elif workflow_key == "EXPENSE_APPROVAL":
        result = _result_by_tool(tool_results, "list_expense_claims")
        rows = result.get("rows", [])
        report["columns"] = [
            "Employee", "Category", "Amount (SAR)", "Claim Date",
            "Receipt", "Policy Flags", "Status",
        ]
        for row in rows:
            flags = list(row.get("policy_flag") or [])
            if isinstance(flags, str):
                flags = [flags]
            # Re-check against the live policy rules (Design 5.4).
            live = expense_policy.check_claim(_claim_stub(row))
            for flag in live:
                if flag not in flags:
                    flags.append(flag)
            report["rows"].append([
                row.get("employee_name"), row.get("category"),
                row.get("amount_sar"), row.get("claim_date"),
                "Yes" if row.get("receipt_attached") else "No",
                "; ".join(flags) if flags else "—",
                row.get("status"),
            ])
            report["claims"].append({
                "claim_id": row.get("id"),
                "employee_name": row.get("employee_name"),
                "amount_sar": row.get("amount_sar"),
                "category": row.get("category"),
                "flags": flags,
                "status": row.get("status"),
            })
            report["approval_items"].append({
                "action_summary": (
                    f"Approve expense claim #{row.get('id')} — "
                    f"{row.get('employee_name')}, "
                    f"{_money(row.get('amount_sar'))} SAR "
                    f"({row.get('category')})."
                ),
                "diff": {"actions": [{
                    "type": "approve_expense_claim",
                    "claim_id": row.get("id"),
                    "amount_sar": row.get("amount_sar"),
                }]},
            })
        report["totals"] = {
            "count": len(rows),
            "total_amount_sar": result.get("total_amount_sar", 0),
        }
    else:
        report["notes"].append(f"No report builder for workflow {workflow_key}.")

    return report


class _ClaimStub:
    """Minimal stand-in so the policy checker can run on tool rows
    without a database round-trip."""

    def __init__(self, row: dict):
        self.category = row.get("category")
        self.amount_sar = row.get("amount_sar") or 0
        self.receipt_attached = bool(row.get("receipt_attached"))


def _claim_stub(row: dict) -> _ClaimStub:
    return _ClaimStub(row)


def export_dir() -> Path:
    path = Path(settings.export_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _export_path(run_id: int, workflow_key: str, fmt: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    filename = f"run_{run_id}_{workflow_key.lower()}_{stamp}.{fmt}"
    return export_dir() / filename


def _write_csv(path: Path, report: dict) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([report["title"]])
        writer.writerow([])
        writer.writerow(report["columns"])
        for row in report["rows"]:
            writer.writerow(["" if value is None else value for value in row])
        writer.writerow([])
        totals = report.get("totals") or {}
        if totals:
            writer.writerow(["Totals", "", f"{totals.get('total_amount_sar', '')}", f"{totals.get('total_vat_sar', '')}"])
        if report.get("notes"):
            writer.writerow([])
            for note in report["notes"]:
                writer.writerow([note])


def _write_xlsx(path: Path, report: dict) -> None:
    book = Workbook()
    sheet = book.active
    sheet.title = "Report"
    sheet.cell(row=1, column=1, value=report["title"]).font = Font(bold=True, size=14)
    header_row = 3
    for col_index, column in enumerate(report["columns"], start=1):
        sheet.cell(row=header_row, column=col_index, value=column).font = Font(bold=True)
    for row_index, row in enumerate(report["rows"], start=header_row + 1):
        for col_index, value in enumerate(row, start=1):
            sheet.cell(row=row_index, column=col_index, value=value)
    totals_row = header_row + 1 + len(report["rows"]) + 1
    totals = report.get("totals") or {}
    if totals:
        sheet.cell(row=totals_row, column=1, value="Totals").font = Font(bold=True)
        if "total_amount_sar" in totals:
            sheet.cell(row=totals_row, column=3, value=totals["total_amount_sar"]).font = Font(bold=True)
        if "total_vat_sar" in totals:
            sheet.cell(row=totals_row, column=4, value=totals["total_vat_sar"]).font = Font(bold=True)
    book.save(path)


def _write_pdf(path: Path, report: dict) -> None:
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        str(path), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=report["title"], author="Al Madar Holding — Enterprise AI Agent",
    )
    story = [Paragraph(report["title"], styles["Title"]), Spacer(1, 6 * mm)]
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    story.append(Paragraph(f"Generated {generated} · Al Madar Holding (fictional demo)", styles["Normal"]))
    story.append(Spacer(1, 4 * mm))
    if report["columns"] and report["rows"]:
        data = [[Paragraph(str(c), styles["Normal"]) for c in report["columns"]]]
        for row in report["rows"]:
            data.append([Paragraph("" if v is None else str(v), styles["Normal"]) for v in row])
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b3d2e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d7dee8")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5fa")]),
        ]))
        story.append(table)
    totals = report.get("totals") or {}
    if totals:
        story.append(Spacer(1, 4 * mm))
        parts = [f"{k.replace('_', ' ')}: {v}" for k, v in totals.items()]
        story.append(Paragraph(" · ".join(parts), styles["Normal"]))
    for note in report.get("notes") or []:
        story.append(Paragraph(note, styles["Normal"]))
    doc.build(story)


_WRITERS = {"csv": _write_csv, "xlsx": _write_xlsx, "pdf": _write_pdf}


def export_report_file(db, run: models.WorkflowRun, fmt: str) -> models.ReportExport:
    """Generate the export file for an approved run from its stored
    report payload and record it in `report_exports`. Raises
    ValueError for an unknown format or a run without a report."""
    if fmt not in EXPORT_FORMATS:
        raise ValueError(f"Unknown export format: {fmt!r}. Use pdf, csv, or xlsx.")
    plan = run.plan or {}
    report = plan.get("report")
    if not report:
        raise ValueError("This run has no report to export.")
    workflow = db.get(models.Workflow, run.workflow_id)
    key = workflow.key if workflow else (report.get("workflow_key") or "report")
    path = _export_path(run.id, key, fmt)
    _WRITERS[fmt](path, report)
    record = models.ReportExport(
        run_id=run.id,
        format=fmt,
        file_path=str(path),
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record
