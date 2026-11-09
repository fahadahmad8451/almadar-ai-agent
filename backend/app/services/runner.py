"""Workflow runner — Sprint 2, LIVE.

Runs the full pipeline for one workflow key:
Supervisor (plan) -> Data Agent (tools) -> Self-Check (verify) ->
Report Agent (build report) -> Approval Agent (create approvals).
The run stops at AWAITING_APPROVAL — nothing executes until a
manager approves. Every step is persisted as a workflow_steps row
and every tool call as a tool_calls row, so the trace is auditable
exactly like the instruct runs in Sprint 1.
"""
import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.agents import subagents
from app.agents.supervisor import _record_step
from app.core.config import settings
from app.core.security import audit
from app.db import models
from app.services import approval as approval_service
from app.services import reports as reports_service
from app.tools import registry as tools_registry

_WORKFLOW_PLANS: dict[str, list] = {
    # (tool, args) — args are filled from run params where marked.
    "INVOICE_REPORT": [
        ("list_invoices", {"status": "PENDING", "period": "all"}),
        ("list_suppliers", {"overdue": True}),
    ],
    "SUPPLIER_FOLLOWUP": [
        ("list_suppliers", {"overdue": True}),
        ("list_invoices", {"status": "OVERDUE", "period": "all"}),
    ],
    "CRM_FOLLOWUP": [
        ("list_leads", {"status": "STALE"}),
        ("list_customers", {}),
    ],
    "EXPENSE_APPROVAL": [
        ("list_expense_claims", {"pending_only": True}),
    ],
}

_INTENT_FOR_WORKFLOW = {v: k for k, v in subagents.INTENT_WORKFLOW.items()}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _plan_for_workflow(workflow_key: str, params: dict) -> list[tuple[str, dict]]:
    """Tool plan for a workflow key, with run params applied."""
    plan = []
    for tool_name, args in _WORKFLOW_PLANS[workflow_key]:
        args = dict(args)
        if workflow_key == "INVOICE_REPORT" and tool_name == "list_invoices":
            if params.get("status"):
                args["status"] = params["status"]
            if params.get("period"):
                args["period"] = params["period"]
        plan.append((tool_name, args))
    return plan


def run_workflow(
    db: Session,
    user: models.User,
    workflow: models.Workflow,
    instruction: str | None = None,
    language: str | None = None,
    params: dict | None = None,
) -> dict:
    """Execute one workflow run through the full pipeline. Returns the
    run summary (run id, status, confidence, approvals created)."""
    params = dict(params or {})
    if not workflow.is_active:
        raise ValueError(f"Workflow {workflow.key} is not active.")
    export_format = params.get("export_format") or reports_service.DEFAULT_FORMAT.get(
        workflow.key, "pdf"
    )
    if export_format not in reports_service.EXPORT_FORMATS:
        raise ValueError(f"Unknown export format: {export_format!r}.")
    language = language or subagents.detect_language(instruction or "")
    instruction = instruction or f"Run workflow {workflow.key}"
    intent = _INTENT_FOR_WORKFLOW.get(workflow.key, "unknown")
    plan = _plan_for_workflow(workflow.key, params)

    run = models.WorkflowRun(
        workflow_id=workflow.id,
        user_id=user.id,
        instruction=instruction,
        language=language,
        status="RUNNING",
        confidence=None,
        plan={
            "tools": [{"tool": name, "args": args} for name, args in plan],
            "export_format": export_format,
        },
        started_at=_now(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    trace: list[dict] = []

    def trace_entry(agent: str, action: str, status: str, latency_ms: int, note: str = "") -> dict:
        entry = {"agent": agent, "action": action, "status": status, "latency_ms": latency_ms, "note": note}
        trace.append(entry)
        return entry

    # Supervisor: plan.
    started = time.monotonic()
    _record_step(
        db, run.id, "supervisor", 0, "plan",
        {"workflow_key": workflow.key, "export_format": export_format},
        {"tools": [name for name, _ in plan]},
        "success", int((time.monotonic() - started) * 1000),
    )
    trace_entry("supervisor", "plan", "success", int((time.monotonic() - started) * 1000), f"{len(plan)} tool(s) planned")

    # Data Agent: execute the plan through the registry.
    tool_results: list[dict] = []
    failures: list[str] = []
    for index, (tool_name, args) in enumerate(plan, start=1):
        step_started = time.monotonic()
        step_id = _record_step(
            db, run.id, "data_agent", index, f"tool:{tool_name}",
            {"tool": tool_name, "args": args}, None, "running",
        )
        try:
            result = tools_registry.execute_tool(db, user, tool_name, args, step_id)
            tool_results.append({"tool": tool_name, "args": args, "result": result})
            step = db.get(models.WorkflowStep, step_id)
            step.status = "success"
            step.output = {"count": result.get("count"), "tool": tool_name}
            step.latency_ms = int((time.monotonic() - step_started) * 1000)
            db.commit()
            trace_entry("data_agent", f"tool:{tool_name}", "success", step.latency_ms)
        except Exception as exc:  # noqa: BLE001 - a failed tool must not kill the run
            failures.append(f"{tool_name}: {exc}")
            step = db.get(models.WorkflowStep, step_id)
            step.status = "failed"
            step.output = {"error": str(exc)}
            step.latency_ms = int((time.monotonic() - step_started) * 1000)
            db.commit()
            trace_entry("data_agent", f"tool:{tool_name}", "failed", step.latency_ms, str(exc))

    # Self-Check: re-compute totals from the raw tool rows.
    check_started = time.monotonic()
    answer = subagents.build_answer(intent, language, tool_results)
    check = subagents.self_check(tool_results, answer)
    if check["notes"]:
        answer["totals"] = check["corrected_totals"]
        answer["summary"] = subagents.render_summary(intent, language, check["corrected_totals"])
    _record_step(
        db, run.id, "self_check", len(trace) + 1, "verify_totals",
        {"totals": answer["totals"]},
        {"passed": check["passed"], "notes": check["notes"]},
        "success" if check["passed"] else "corrected",
        int((time.monotonic() - check_started) * 1000),
    )
    trace_entry(
        "self_check", "verify_totals",
        "success" if check["passed"] else "corrected",
        int((time.monotonic() - check_started) * 1000),
        "; ".join(check["notes"]) if check["notes"] else "totals verified",
    )

    # Confidence (same rules as the instruct flow).
    if not tool_results:
        confidence = 0.0
        status = "FAILED"
    elif failures:
        confidence = 0.7
        status = "COMPLETED"
    elif not check["passed"]:
        confidence = 0.9
        status = "COMPLETED"
    else:
        confidence = 1.0
        status = "COMPLETED"
    escalated = confidence < settings.confidence_threshold
    if escalated and status == "COMPLETED":
        status = "ESCALATED"

    approval_ids: list[int] = []
    report = None
    if status == "COMPLETED":
        # Report Agent: build the report payload from the tool results.
        report_started = time.monotonic()
        report = reports_service.build_report(
            workflow.key, language, tool_results, export_format, db
        )
        plan = dict(run.plan or {})
        plan["report"] = report
        run.plan = plan
        db.commit()
        _record_step(
            db, run.id, "report_agent", len(trace) + 1, "build_report",
            {"workflow_key": workflow.key},
            {"title": report["title"], "rows": len(report["rows"])},
            "success", int((time.monotonic() - report_started) * 1000),
        )
        trace_entry(
            "report_agent", "build_report", "success",
            int((time.monotonic() - report_started) * 1000),
            f"{len(report['rows'])} row(s), {len(report['approval_items'])} approval item(s)",
        )
        # Approval Agent: one approval row per approval item.
        approvals = approval_service.create_approvals_for_run(db, run, user, report)
        approval_ids = [a.id for a in approvals]
        _record_step(
            db, run.id, "approval_agent", len(trace) + 1, "create_approvals",
            {"approval_ids": approval_ids},
            {"count": len(approval_ids)},
            "success", 0,
        )
        trace_entry(
            "approval_agent", "create_approvals", "success", 0,
            f"{len(approval_ids)} approval(s) created",
        )
        status = "AWAITING_APPROVAL" if approval_ids else "COMPLETED"

    run.status = status
    run.confidence = confidence
    run.finished_at = _now()
    db.commit()
    audit(
        db,
        user_id=user.id,
        action="WORKFLOW_RUN",
        resource=f"workflows/{workflow.key}/run",
        result=status,
        details={
            "run_id": run.id,
            "workflow_key": workflow.key,
            "confidence": confidence,
            "approval_ids": approval_ids,
        },
    )
    return {
        "run_id": run.id,
        "workflow_key": workflow.key,
        "status": status,
        "confidence": confidence,
        "escalated": escalated,
        "summary": answer.get("summary", ""),
        "totals": answer.get("totals", {}),
        "approval_ids": approval_ids,
        "report_title": (report or {}).get("title"),
        "trace": trace,
    }
