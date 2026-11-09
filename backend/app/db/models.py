"""SQLAlchemy models — Design section 4 (17 tables).

Setup v0.1: models only. No engine is created anywhere in v0.1 and no
query runs — the database is wired in Sprint 1. The models import
cleanly without PostgreSQL, pgvector, or any database server running.

Notes on types:
- JSONB in the design is JSON here (portable). Sprint 1 switches the
  columns to PostgreSQL JSONB.
- agent_memory.embedding is JSON here. Sprint 1 stores a real
  pgvector vector(1024) for similarity recall.
- expense_claims is NOT in the design's table list — it was added in
  Setup v0.1 because the EXPENSE_APPROVAL workflow (Design 5.4) reads
  pending claims. Design gap, fixed here and reported to Fahad.
"""
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    # Roles: ADMIN, OPERATIONS_MANAGER, OPERATIONS_OFFICER
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, nullable=False)


class ErpSupplier(Base):
    __tablename__ = "erp_suppliers"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    name_ar = Column(String(255))
    contact_email = Column(String(255))
    payment_terms = Column(String(100))
    created_at = Column(DateTime, nullable=False)


class ErpInvoice(Base):
    __tablename__ = "erp_invoices"
    # Status: PENDING, PAID, OVERDUE, DISPUTED
    id = Column(Integer, primary_key=True)
    invoice_no = Column(String(100), unique=True, nullable=False)
    supplier_id = Column(Integer, ForeignKey("erp_suppliers.id"), nullable=False)
    amount_sar = Column(Float, nullable=False)
    vat_sar = Column(Float, nullable=False)
    issue_date = Column(DateTime, nullable=False)
    due_date = Column(DateTime, nullable=False)
    status = Column(String(50), nullable=False)
    po_no = Column(String(100))
    created_at = Column(DateTime, nullable=False)


class CrmCustomer(Base):
    __tablename__ = "crm_customers"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    name_ar = Column(String(255))
    email = Column(String(255))
    segment = Column(String(100))
    last_contact_at = Column(DateTime)
    created_at = Column(DateTime, nullable=False)


class CrmLead(Base):
    __tablename__ = "crm_leads"
    # Status: NEW, CONTACTED, STALE, CONVERTED, LOST
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255))
    source = Column(String(100))
    status = Column(String(50), nullable=False)
    score = Column(Integer, default=0)
    last_activity_at = Column(DateTime)
    created_at = Column(DateTime, nullable=False)


class CrmDeal(Base):
    __tablename__ = "crm_deals"
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("crm_customers.id"), nullable=False)
    title = Column(String(255), nullable=False)
    amount_sar = Column(Float, nullable=False)
    stage = Column(String(100), nullable=False)
    expected_close = Column(DateTime)
    created_at = Column(DateTime, nullable=False)


class Workflow(Base):
    __tablename__ = "workflows"
    # Key: INVOICE_REPORT, SUPPLIER_FOLLOWUP, CRM_FOLLOWUP, EXPENSE_APPROVAL
    # Trigger type: MANUAL, SCHEDULED
    id = Column(Integer, primary_key=True)
    key = Column(String(100), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    name_ar = Column(String(255))
    description = Column(Text)
    trigger_type = Column(String(50), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, nullable=False)


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    # Status: RUNNING, AWAITING_APPROVAL, APPROVED, REJECTED, COMPLETED, FAILED, ESCALATED
    id = Column(Integer, primary_key=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    instruction = Column(Text, nullable=False)
    language = Column(String(10), default="en")
    status = Column(String(50), nullable=False)
    confidence = Column(Float)
    plan = Column(JSON)
    started_at = Column(DateTime, nullable=False)
    finished_at = Column(DateTime)


class WorkflowStep(Base):
    __tablename__ = "workflow_steps"
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("workflow_runs.id"), nullable=False)
    agent = Column(String(100), nullable=False)
    step_index = Column(Integer, nullable=False)
    action = Column(String(255), nullable=False)
    input = Column(JSON)
    output = Column(JSON)
    status = Column(String(50), nullable=False)
    latency_ms = Column(Integer)
    tokens = Column(Integer)
    created_at = Column(DateTime, nullable=False)


class ToolCall(Base):
    __tablename__ = "tool_calls"
    # The forensic record of everything the agent did.
    id = Column(Integer, primary_key=True)
    step_id = Column(Integer, ForeignKey("workflow_steps.id"), nullable=False)
    tool_name = Column(String(255), nullable=False)
    args = Column(JSON)
    result = Column(JSON)
    status = Column(String(50), nullable=False)
    error = Column(Text)
    created_at = Column(DateTime, nullable=False)


class Approval(Base):
    __tablename__ = "approvals"
    # Status: PENDING, APPROVED, REJECTED. diff shows exactly what will execute.
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("workflow_runs.id"), nullable=False)
    requested_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    approver_id = Column(Integer, ForeignKey("users.id"))
    action_summary = Column(Text, nullable=False)
    diff = Column(JSON)
    status = Column(String(50), nullable=False)
    decided_at = Column(DateTime)
    comment = Column(Text)


class EmailDraft(Base):
    __tablename__ = "email_drafts"
    # Status: DRAFT, APPROVED, SENT (SENT is never reached — no real sending).
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("workflow_runs.id"), nullable=False)
    to_email = Column(String(255), nullable=False)
    subject = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    status = Column(String(50), nullable=False)
    created_at = Column(DateTime, nullable=False)


class ReportExport(Base):
    __tablename__ = "report_exports"
    # Format: PDF, CSV, XLSX
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("workflow_runs.id"), nullable=False)
    format = Column(String(20), nullable=False)
    file_path = Column(String(500), nullable=False)
    created_at = Column(DateTime, nullable=False)


class AgentMemory(Base):
    __tablename__ = "agent_memory"
    # Kind: PREFERENCE, FACT, OUTCOME. embedding is JSON in v0.1;
    # Sprint 1 stores a pgvector vector(1024) for similarity recall.
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    kind = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(JSON)
    source_run_id = Column(Integer, ForeignKey("workflow_runs.id"))
    created_at = Column(DateTime, nullable=False)


class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"
    # cron: standard 5-field expression, e.g. morning invoice check.
    id = Column(Integer, primary_key=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=False)
    cron = Column(String(100), nullable=False)
    next_run_at = Column(DateTime)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    # Action: LOGIN, INSTRUCT, TOOL_CALL, APPROVE, REJECT, EXECUTE, ACCESS_DENIED
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    action = Column(String(100), nullable=False)
    resource = Column(String(255))
    result = Column(String(50), nullable=False)
    details = Column(JSON)
    ip = Column(String(100))
    created_at = Column(DateTime, nullable=False)


class ExpenseClaim(Base):
    __tablename__ = "expense_claims"
    # NOTE: added in Setup v0.1 — the design's table list omitted it, but
    # the EXPENSE_APPROVAL workflow (Design 5.4) reads pending claims.
    # Status: PENDING, APPROVED, REJECTED, FLAGGED
    id = Column(Integer, primary_key=True)
    employee_name = Column(String(255), nullable=False)
    employee_email = Column(String(255), nullable=False)
    category = Column(String(100), nullable=False)
    amount_sar = Column(Float, nullable=False)
    claim_date = Column(DateTime, nullable=False)
    receipt_attached = Column(Boolean, default=False)
    policy_flag = Column(String(255))
    status = Column(String(50), nullable=False)
    created_at = Column(DateTime, nullable=False)


class EvalResult(Base):
    __tablename__ = "eval_results"
    id = Column(Integer, primary_key=True)
    scenario = Column(String(255), nullable=False)
    workflow_key = Column(String(100), nullable=False)
    success = Column(Boolean, nullable=False)
    tool_accuracy = Column(Float)
    approval_compliant = Column(Boolean)
    self_check_catch = Column(Boolean)
    latency_ms = Column(Integer)
    tokens = Column(Integer)
    run_at = Column(DateTime, nullable=False)


class RequestMetric(Base):
    """One row per HTTP request served — Monitoring (v0.9.0).

    Written by middleware in app/main.py (own session, fail-open, so
    a metrics write can never break the request it measures). No
    request bodies, instruction text, tokens or passwords are stored —
    only the endpoint (id-like segments collapsed to {id}), method,
    status, latency and the caller's role.
    """
    __tablename__ = "request_metrics"
    id = Column(Integer, primary_key=True)
    endpoint = Column(String(255), nullable=False)
    method = Column(String(10), nullable=False)
    status = Column(Integer, nullable=False)
    latency_ms = Column(Integer, nullable=False)
    role = Column(String(50))
    created_at = Column(DateTime, nullable=False)


class Alert(Base):
    """Monitoring alert — Monitoring (v0.9.0).

    Rule: one of instruct_p95_latency, error_rate_5xx, eval_suite_fail,
    pending_approvals_backlog, scheduler_missed_fire, api_down,
    database_unavailable. Status ACTIVE until the condition clears
    (auto-resolved by the checker) or an Admin resolves it by hand.
    """
    __tablename__ = "alerts"
    id = Column(Integer, primary_key=True)
    rule = Column(String(100), nullable=False)
    severity = Column(String(20), nullable=False)
    message = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="ACTIVE")
    details = Column(JSON)
    created_at = Column(DateTime, nullable=False)
    resolved_at = Column(DateTime)
    resolved_by = Column(Integer, ForeignKey("users.id"))


ALL_MODELS = [
    User, ErpSupplier, ErpInvoice, CrmCustomer, CrmLead, CrmDeal,
    Workflow, WorkflowRun, WorkflowStep, ToolCall, Approval, EmailDraft,
    ReportExport, AgentMemory, ScheduledJob, AuditLog, EvalResult,
    ExpenseClaim, RequestMetric, Alert,
]
