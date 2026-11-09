"""Tool registry + executor — Sprint 2.

Every tool declares its name, description, allowed roles, and
side-effect class (Design section 2). The executor is the single choke
point for tool use:
- unknown tool -> ToolError (404-style, no execution);
- role not allowed -> PermissionError (HTTP 403 at the API layer);
- write tools without a valid human approval token -> the call is
  recorded as `refused` and ApprovalRequiredError is raised; the
  token is the id of a PENDING approval whose diff covers the exact
  action for the run (verified by the Approval Agent);
- every call is recorded in the tool_calls table (the forensic record),
  with retries (max 3) on transient failures.
"""
import json
import time

from sqlalchemy.orm import Session

from app.core.security import ALL_ROLES, CAN_APPROVE
from app.db import models
from app.tools import crm as crm_tools
from app.tools import erp as erp_tools
from app.tools import writes as write_tools


class ToolError(Exception):
    """Unknown tool or bad arguments."""


class ApprovalRequiredError(Exception):
    """A write tool was called without a human approval token."""


class ToolDefinition:
    def __init__(self, name, description, func, allowed_roles, side_effect):
        self.name = name
        self.description = description
        self.func = func
        self.allowed_roles = tuple(allowed_roles)
        self.side_effect = side_effect  # "read" or "write"


TOOL_REGISTRY: dict[str, ToolDefinition] = {
    "list_invoices": ToolDefinition(
        "list_invoices",
        "List ERP invoices, optionally filtered by status and period.",
        erp_tools.list_invoices,
        ALL_ROLES,
        "read",
    ),
    "list_suppliers": ToolDefinition(
        "list_suppliers",
        "List suppliers; overdue=True returns only suppliers with overdue invoices.",
        erp_tools.list_suppliers,
        ALL_ROLES,
        "read",
    ),
    "get_purchase_order": ToolDefinition(
        "get_purchase_order",
        "Return the invoices recorded against one purchase order number.",
        erp_tools.get_purchase_order,
        ALL_ROLES,
        "read",
    ),
    "list_customers": ToolDefinition(
        "list_customers",
        "List all CRM customers.",
        crm_tools.list_customers,
        ALL_ROLES,
        "read",
    ),
    "list_leads": ToolDefinition(
        "list_leads",
        "List CRM leads, optionally filtered by status.",
        crm_tools.list_leads,
        ALL_ROLES,
        "read",
    ),
    "list_expense_claims": ToolDefinition(
        "list_expense_claims",
        "List expense claims awaiting a decision.",
        crm_tools.list_expense_claims,
        ALL_ROLES,
        "read",
    ),
    "export_report": ToolDefinition(
        "export_report",
        "Generate a report export file (PDF/CSV/XLSX) for an approved run. "
        "WRITE tool: Operations Manager/Admin only, and only with a human approval token.",
        write_tools.export_report,
        CAN_APPROVE,
        "write",
    ),
    "save_email_draft": ToolDefinition(
        "save_email_draft",
        "Save one email draft as APPROVED. Drafts are never sent. "
        "WRITE tool: Operations Manager/Admin only, and only with a human approval token.",
        write_tools.save_email_draft,
        CAN_APPROVE,
        "write",
    ),
    "approve_expense_claim": ToolDefinition(
        "approve_expense_claim",
        "Approve one expense claim. WRITE tool: Operations Manager/Admin only, "
        "and only with a human approval token.",
        write_tools.approve_expense_claim,
        CAN_APPROVE,
        "write",
    ),
    "record_invoice": ToolDefinition(
        "record_invoice",
        "Record one invoice in ERP (PENDING if matched, DISPUTED if "
        "mismatched) after a manager approved the match report. WRITE "
        "tool: Operations Manager/Admin only, and only with a human "
        "approval token. Idempotent on invoice_no.",
        write_tools.record_invoice,
        CAN_APPROVE,
        "write",
    ),
}


def tools_for_role(role: str) -> list[str]:
    """Tool names the Supervisor may plan for a user with this role."""
    return [name for name, tool in TOOL_REGISTRY.items() if role in tool.allowed_roles]


def _serialisable(value, limit: int = 200_000) -> object:
    try:
        text = json.dumps(value, default=str)
    except (TypeError, ValueError):
        return {"note": "result is not JSON-serialisable"}
    if len(text) > limit:
        return {"note": "result truncated for storage", "bytes": len(text)}
    return json.loads(text)


def execute_tool(
    db: Session,
    user: models.User,
    tool_name: str,
    args: dict | None,
    step_id: int,
    max_retries: int = 3,
    approval_token: int | None = None,
) -> dict:
    """Execute one tool call with permission checks, retries, and a
    forensic tool_calls row. Returns the tool result dict.

    Write tools need `approval_token`: the id of a PENDING approval
    whose diff covers this exact action for this run. Without a valid
    token the call is recorded as `refused` and never executes.
    """
    args = dict(args or {})
    tool = TOOL_REGISTRY.get(tool_name)
    if tool is None:
        raise ToolError(f"Unknown tool: {tool_name!r}.")
    if user.role not in tool.allowed_roles:
        _record(db, step_id, tool_name, args, "forbidden", None, "Role not allowed.")
        raise PermissionError(
            f"Role {user.role} may not call tool {tool_name}."
        )
    if tool.side_effect == "write":
        if approval_token is None:
            _record(
                db,
                step_id,
                tool_name,
                args,
                "refused",
                None,
                "Write tools require a human approval token.",
            )
            raise ApprovalRequiredError(
                f"Tool {tool_name} requires a human approval token."
            )
        # Deferred import: the Approval Agent imports this registry.
        from app.services.approval import verify_approval_token

        step = db.get(models.WorkflowStep, step_id)
        run_id = step.run_id if step is not None else None
        try:
            verify_approval_token(db, approval_token, run_id, tool_name)
        except Exception as exc:  # noqa: BLE001 - any token failure refuses the call
            _record(db, step_id, tool_name, args, "refused", None, str(exc))
            raise ApprovalRequiredError(str(exc)) from exc

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            started = time.monotonic()
            result = tool.func(db, **args)
            _record(
                db,
                step_id,
                tool_name,
                args,
                "success",
                _serialisable(result),
                None,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
            return result
        except (ValueError, TypeError) as exc:
            # Bad arguments: retrying will not help.
            _record(db, step_id, tool_name, args, "failed", None, str(exc))
            raise ToolError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - transient DB errors are retried
            last_error = exc
            if attempt == max_retries:
                _record(db, step_id, tool_name, args, "failed", None, str(exc))
                raise ToolError(f"Tool {tool_name} failed after {max_retries} attempts: {exc}") from exc
            time.sleep(0.2 * attempt)
    raise ToolError(str(last_error) if last_error else "Tool failed.")


def _record(
    db: Session,
    step_id: int,
    tool_name: str,
    args: dict,
    status: str,
    result: object,
    error: str | None,
    latency_ms: int | None = None,
) -> None:
    from datetime import datetime, timezone

    db.add(
        models.ToolCall(
            step_id=step_id,
            tool_name=tool_name,
            args=_serialisable(args),
            result=result,
            status=status,
            error=error,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
    )
    db.commit()
