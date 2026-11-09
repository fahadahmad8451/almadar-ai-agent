"""Seed the database with realistic synthetic data.

Al Madar Holding (fictional) operations data — Saudi suppliers,
invoices with 15% VAT, CRM customers/leads/deals, expense claims,
demo users, the 4 core workflows and the 3 locked scheduled jobs.

Everything is synthetic. No real customer, supplier, or financial
data. Amounts and dates are fixed (seeded RNG + fixed reference date
2026-11-06) so repeated runs produce identical data.

Idempotent: clears the seeded tables first, then inserts.
Usage (from the project root):
    python scripts/seed.py
Requires: local PostgreSQL running with database almadar_agent
(see docs/SETUP.md). Demo passwords below are DEMO ONLY.
"""
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from passlib.context import CryptContext  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import models  # noqa: E402
from app.db.session import SessionLocal, engine, init_db  # noqa: E402

RANDOM = random.Random(42)
TODAY = datetime(2026, 11, 6)
PWD = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Demo accounts — DEMO ONLY. Disabled in production (same rule as Project 1).
DEMO_USERS = [
    ("admin@almadar.local", "AMH Admin", "ADMIN", "Admin123!"),
    ("manager@almadar.local", "Layla Alsubaie", "OPERATIONS_MANAGER", "Manager123!"),
    ("ops@almadar.local", "Omar Aljaber", "OPERATIONS_OFFICER", "Ops123!"),
]

SUPPLIERS = [
    ("Al Rajhi Office Supplies Co.", "الراجحي للوازم المكاتب", "orders@alrajhisupplies.com.sa", "Net 30"),
    ("Saudi Tech Trading Est.", "السعودية التقنية للتجارة", "sales@sauditechtrading.com.sa", "Net 45"),
    ("Al Noor Cleaning Services", "النور لخدمات التنظيف", "contracts@alnoorcleaning.com.sa", "Net 30"),
    ("Kingdom Catering Co.", "المملكة للتموين", "info@kingdomcatering.com.sa", "Net 15"),
    ("Sahara Logistics LLC", "الصحراء للوجستيات", "ops@saharalogistics.com.sa", "Net 30"),
    ("Al Amal Printing Press", "الأمل للطباعة", "print@alamalpress.com.sa", "Net 30"),
    ("Falcon Security Services", "الصقر للخدمات الأمنية", "service@falconsecurity.com.sa", "Net 45"),
    ("Riyadh Water & Utilities Co.", "الرياض للمياه والمرافق", "billing@riyadhutilities.com.sa", "Net 30"),
    ("Golden Falcon Transport", "الصقر الذهبي للنقل", "dispatch@goldenfalcon.com.sa", "Net 15"),
    ("Naseem IT Solutions", "نسيم لحلول تقنية المعلومات", "support@naseemitsolutions.com.sa", "Net 30"),
]

CUSTOMERS = [
    ("Al Safa Retail Group", "الصفا للتجزئة", "finance@alsafaretail.com.sa", "Retail"),
    ("Jeddah Foods Trading", "جدة للأغذية والتجارة", "accounts@jeddahfoods.com.sa", "Food Distribution"),
    ("Riyadh Medical Center", "مركز الرياض الطبي", "admin@riyadhmedical.com.sa", "Healthcare"),
    ("Al Qassim Construction", "القصيم للمقاولات", "finance@alqassimconst.com.sa", "Construction"),
    ("Eastern Petrochemical Services", "الشرقية للخدمات البتروكيماوية", "ops@easternpetro.com.sa", "Energy"),
    ("Makkah Hospitality Group", "مكة للضيافة", "reservations@makkahhospitality.com.sa", "Hospitality"),
    ("Tabuk Agriculture Co.", "تبوك الزراعية", "info@tabukagri.com.sa", "Agriculture"),
    ("Dammam Electronics Market", "سوق الدمام للإلكترونيات", "sales@dammamelectronics.com.sa", "Retail"),
]

LEADS = [
    ("Khalid Alotaibi", "khalid.alotaibi@example.com", "Website", "STALE", 42),
    ("Sara Alqahtani", "sara.alqahtani@example.com", "Referral", "CONTACTED", 68),
    ("Mohammed Alharbi", "mohammed.alharbi@example.com", "Trade Show", "NEW", 55),
    ("Noura Alshammari", "noura.alshammari@example.com", "Website", "STALE", 31),
    ("Faisal Aldossary", "faisal.aldossary@example.com", "Partner", "CONTACTED", 74),
    ("Reem Almutairi", "reem.almutairi@example.com", "Website", "NEW", 48),
    ("Turki Alrashid", "turki.alrashid@example.com", "Referral", "STALE", 25),
    ("Layla Alsubaie", "layla.alsubaie@example.com", "Trade Show", "CONVERTED", 88),
    ("Omar Aljaber", "omar.aljaber@example.com", "Website", "LOST", 12),
    ("Huda Alghamdi", "huda.alghamdi@example.com", "Partner", "STALE", 37),
]

# (employee, email, category, amount, days_ago, receipt, flag, status)
EXPENSE_CLAIMS = [
    ("Ahmed Alotaibi", "ahmed.alotaibi@almadar.local", "Travel", 4200.00, 5, True, None, "PENDING"),
    ("Sara Alqahtani", "sara.alqahtani@almadar.local", "Meals", 280.00, 3, True, None, "PENDING"),
    ("Khalid Alharbi", "khalid.alharbi@almadar.local", "Office supplies", 1850.00, 8, True, None, "PENDING"),
    ("Mona Alshammari", "mona.alshammari@almadar.local", "Training", 2900.00, 12, True, None, "PENDING"),
    ("Faisal Nasser", "faisal.nasser@almadar.local", "Travel", 6100.00, 6, True, "Over category limit (5,000 SAR)", "FLAGGED"),
    ("Ahmed Alotaibi", "ahmed.alotaibi@almadar.local", "Other", 950.00, 2, False, "Missing receipt", "FLAGGED"),
    ("Sara Alqahtani", "sara.alqahtani@almadar.local", "Travel", 3800.00, 15, True, None, "APPROVED"),
    ("Khalid Alharbi", "khalid.alharbi@almadar.local", "Meals", 240.00, 9, True, None, "APPROVED"),
    ("Mona Alshammari", "mona.alshammari@almadar.local", "Office supplies", 1450.00, 20, True, None, "REJECTED"),
    ("Faisal Nasser", "faisal.nasser@almadar.local", "Training", 3100.00, 11, True, "Over category limit (3,000 SAR)", "FLAGGED"),
]

WORKFLOWS = [
    ("INVOICE_REPORT", "Pending Invoices Report", "تقرير الفواتير المعلقة",
     "Build a pending-invoices report with overdue suppliers.", "MANUAL"),
    ("SUPPLIER_FOLLOWUP", "Overdue Supplier Follow-up", "متابعة الموردين المتأخرين",
     "Draft reminder emails for overdue suppliers (approval required).", "MANUAL"),
    ("CRM_FOLLOWUP", "CRM Follow-up", "متابعة إدارة علاقات العملاء",
     "Prioritised follow-up list for stale leads and inactive customers.", "MANUAL"),
    ("EXPENSE_APPROVAL", "Expense Approval", "اعتماد المصروفات",
     "Summarise pending expense claims with policy flags for approval.", "MANUAL"),
]

# Locked scheduled jobs (Design decisions, 2026-11-06): daily invoice
# check 08:00, weekly CRM digest Monday 09:00, month-end summary 1st 09:00.
SCHEDULED_JOBS = [
    ("INVOICE_REPORT", "0 8 * * *"),
    ("CRM_FOLLOWUP", "0 9 * * 1"),
    ("SUPPLIER_FOLLOWUP", "0 9 1 * *"),
]


def _vat(amount: float) -> float:
    return round(amount * 0.15, 2)


def seed(include_demo_users: bool = True) -> dict:
    init_db()
    db = SessionLocal()
    counts = {}
    try:
        # Clear in dependency-safe order (children first).
        # TRUNCATE ... RESTART IDENTITY resets the id sequences, so a
        # re-seed restores the same ids (workflows 1-4, jobs 1-3) and
        # nothing that relies on seeded ids breaks after a re-seed.
        tables = ", ".join(
            f'"{model.__tablename__}"'
            for model in (models.ToolCall, models.WorkflowStep, models.Approval,
                          models.EmailDraft, models.ReportExport, models.AgentMemory,
                          models.WorkflowRun, models.ScheduledJob, models.EvalResult,
                          models.AuditLog, models.ExpenseClaim, models.CrmDeal,
                          models.CrmLead, models.CrmCustomer, models.ErpInvoice,
                          models.ErpSupplier, models.Workflow, models.User)
        )
        db.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
        db.commit()

        if include_demo_users:
            for email, name, role, password in DEMO_USERS:
                db.add(models.User(email=email, name=name, role=role,
                                   password_hash=PWD.hash(password), created_at=TODAY))
            db.flush()
            counts["users"] = len(DEMO_USERS)
        else:
            # Production: no demo accounts at all. The first Admin is
            # created with scripts/create_admin.py instead.
            counts["users"] = 0

        supplier_ids = []
        for name, name_ar, email, terms in SUPPLIERS:
            row = models.ErpSupplier(name=name, name_ar=name_ar, contact_email=email,
                                     payment_terms=terms, created_at=TODAY)
            db.add(row)
            db.flush()
            supplier_ids.append(row.id)
        counts["suppliers"] = len(SUPPLIERS)

        # 24 invoices: 12 PENDING, 6 PAID, 4 OVERDUE, 2 DISPUTED.
        statuses = (["PENDING"] * 12 + ["PAID"] * 6 + ["OVERDUE"] * 4 + ["DISPUTED"] * 2)
        RANDOM.shuffle(statuses)
        for i, status in enumerate(statuses, start=1):
            supplier_id = supplier_ids[(i - 1) % len(supplier_ids)]
            amount = round(RANDOM.uniform(1200, 85000), 2)
            issue = TODAY - timedelta(days=RANDOM.randint(10, 60))
            if status == "OVERDUE":
                due = TODAY - timedelta(days=RANDOM.randint(1, 25))
            elif status == "PAID":
                due = TODAY - timedelta(days=RANDOM.randint(1, 40))
            else:
                due = TODAY + timedelta(days=RANDOM.randint(3, 45))
            db.add(models.ErpInvoice(
                invoice_no=f"INV-2026-{1000 + i}",
                supplier_id=supplier_id, amount_sar=amount, vat_sar=_vat(amount),
                issue_date=issue, due_date=due, status=status,
                po_no=f"PO-2026-{2000 + i}", created_at=issue))
        counts["invoices"] = len(statuses)

        for name, name_ar, email, segment in CUSTOMERS:
            db.add(models.CrmCustomer(
                name=name, name_ar=name_ar, email=email, segment=segment,
                last_contact_at=TODAY - timedelta(days=RANDOM.randint(2, 50)),
                created_at=TODAY - timedelta(days=RANDOM.randint(60, 300))))
        db.flush()
        counts["customers"] = len(CUSTOMERS)

        for name, email, source, status, score in LEADS:
            db.add(models.CrmLead(
                name=name, email=email, source=source, status=status, score=score,
                last_activity_at=TODAY - timedelta(days=RANDOM.randint(1, 90)),
                created_at=TODAY - timedelta(days=RANDOM.randint(30, 200))))
        counts["leads"] = len(LEADS)

        customer_ids = [c.id for c in db.query(models.CrmCustomer).all()]
        deal_stages = ["Prospecting", "Negotiation", "Proposal", "Closed Won", "Closed Lost"]
        for i in range(6):
            db.add(models.CrmDeal(
                customer_id=customer_ids[i % len(customer_ids)],
                title=f"Corporate services package — {CUSTOMERS[i % len(CUSTOMERS)][0]}",
                amount_sar=round(RANDOM.uniform(50000, 400000), 2),
                stage=deal_stages[i % len(deal_stages)],
                expected_close=TODAY + timedelta(days=RANDOM.randint(10, 90)),
                created_at=TODAY - timedelta(days=RANDOM.randint(20, 120))))
        counts["deals"] = 6

        for name, email, category, amount, days_ago, receipt, flag, status in EXPENSE_CLAIMS:
            db.add(models.ExpenseClaim(
                employee_name=name, employee_email=email, category=category,
                amount_sar=amount, claim_date=TODAY - timedelta(days=days_ago),
                receipt_attached=receipt, policy_flag=flag, status=status,
                created_at=TODAY - timedelta(days=days_ago)))
        counts["expense_claims"] = len(EXPENSE_CLAIMS)

        workflow_ids = {}
        for key, name, name_ar, description, trigger in WORKFLOWS:
            row = models.Workflow(key=key, name=name, name_ar=name_ar,
                                  description=description, trigger_type=trigger,
                                  is_active=True, created_at=TODAY)
            db.add(row)
            db.flush()
            workflow_ids[key] = row.id
        counts["workflows"] = len(WORKFLOWS)

        for key, cron in SCHEDULED_JOBS:
            db.add(models.ScheduledJob(workflow_id=workflow_ids[key], cron=cron,
                                       next_run_at=TODAY + timedelta(days=1),
                                       is_active=True, created_at=TODAY))
        counts["scheduled_jobs"] = len(SCHEDULED_JOBS)

        db.commit()
    finally:
        db.close()
    return counts


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Seed the Al Madar database.")
    parser.add_argument(
        "--no-demo-users",
        action="store_true",
        help="Seed business data without the demo accounts (production).",
    )
    args = parser.parse_args()
    result = seed(include_demo_users=not args.no_demo_users)
    from app.core.config import settings  # noqa: E402

    db_name = settings.database_url.rsplit("/", 1)[-1]
    print(f"Seed complete (database: {db_name}):")
    for table, count in result.items():
        print(f"  {table}: {count}")
