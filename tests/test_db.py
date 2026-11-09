"""Database tests — Setup v0.1 (requires a seeded database).

Run `python scripts/seed.py` first (CI does this). These tests prove
the database is real PostgreSQL with the seeded data — not models on
paper. If PostgreSQL is down, they fail loudly instead of passing on
a fake fallback.
"""
from sqlalchemy import inspect, text

from app.db import models
from app.db.session import engine


def test_all_tables_exist():
    tables = set(inspect(engine).get_table_names())
    expected = {m.__tablename__ for m in models.ALL_MODELS}
    assert len(models.ALL_MODELS) == 20
    assert expected.issubset(tables), f"missing tables: {expected - tables}"


def test_seed_counts():
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM users")).scalar() == 3
        assert conn.execute(text("SELECT COUNT(*) FROM erp_suppliers")).scalar() == 10
        assert conn.execute(text("SELECT COUNT(*) FROM erp_invoices")).scalar() == 24
        assert conn.execute(text("SELECT COUNT(*) FROM crm_customers")).scalar() == 8
        assert conn.execute(text("SELECT COUNT(*) FROM crm_leads")).scalar() == 10
        assert conn.execute(text("SELECT COUNT(*) FROM crm_deals")).scalar() == 6
        assert conn.execute(text("SELECT COUNT(*) FROM expense_claims")).scalar() == 10
        assert conn.execute(text("SELECT COUNT(*) FROM workflows")).scalar() == 4
        assert conn.execute(text("SELECT COUNT(*) FROM scheduled_jobs")).scalar() == 3


def test_invoice_vat_is_15_percent():
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT amount_sar, vat_sar FROM erp_invoices")).all()
    assert len(rows) == 24
    for amount, vat in rows:
        assert abs(vat - round(amount * 0.15, 2)) < 0.01


def test_invoice_statuses_cover_all_states():
    with engine.connect() as conn:
        statuses = {
            r[0] for r in conn.execute(text("SELECT DISTINCT status FROM erp_invoices")).all()
        }
    assert statuses == {"PENDING", "PAID", "OVERDUE", "DISPUTED"}
