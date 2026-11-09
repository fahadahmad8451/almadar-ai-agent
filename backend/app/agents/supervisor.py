"""Supervisor agent — Sprint 1, LIVE (LangGraph).

Graph: parse_intent -> data_agent -> self_check -> finalize.
Unknown intent goes straight from parse_intent to finalize with a
clarification answer (no workflow run is created for it).

Sprint 1 scope: the Data Agent only. Report Agent and Approval Agent
arrive in later sprints — this graph answers data questions and stops
before any approval or execution. Every step is persisted as a
workflow_steps row and every tool call as a tool_calls row; the run
itself is a workflow_runs row, so the trace is fully auditable.
"""
import time
from datetime import datetime, timezone
from typing import TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from app.agents import subagents
from app.core.config import settings
from app.core.security import audit
from app.db import models
from app.tools import registry as tools_registry


class AgentState(TypedDict, total=False):
    instruction: str
    language: str
    user: models.User
    db: Session
    intent: str
    parser: str
    plan: list
    tool_results: list
    tool_failures: list
    answer: dict
    self_check: dict
    confidence: float
    escalated: bool
    run_id: int | None
    status: str
    trace: list


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _record_step(
    db: Session,
    run_id: int,
    agent: str,
    index: int,
    action: str,
    input_data: dict | None,
    output_data: dict | None,
    status: str,
    latency_ms: int | None = None,
) -> int:
    step = models.WorkflowStep(
        run_id=run_id,
        agent=agent,
        step_index=index,
        action=action,
        input=input_data or {},
        output=output_data or {},
        status=status,
        latency_ms=latency_ms,
        created_at=_now(),
    )
    db.add(step)
    db.commit()
    db.refresh(step)
    return step.id


def _trace_entry(agent: str, action: str, status: str, latency_ms: int, note: str = "") -> dict:
    return {
        "agent": agent,
        "action": action,
        "status": status,
        "latency_ms": latency_ms,
        "note": note,
    }


def _parse_intent_node(state: AgentState) -> AgentState:
    started = time.monotonic()
    language = state.get("language") or subagents.detect_language(state["instruction"])
    intent, parser = subagents.parse_intent(state["instruction"])
    state["language"] = language
    state["intent"] = intent
    state["parser"] = parser
    state["plan"] = subagents.plan_for_intent(intent, state["instruction"])
    state["trace"].append(
        _trace_entry(
            "supervisor",
            "parse_intent",
            "success",
            int((time.monotonic() - started) * 1000),
            f"intent={intent} parser={parser}",
        )
    )
    return state


def _data_agent_node(state: AgentState) -> AgentState:
    db: Session = state["db"]
    user: models.User = state["user"]
    started = time.monotonic()
    workflow = (
        db.query(models.Workflow)
        .filter(models.Workflow.key == subagents.INTENT_WORKFLOW[state["intent"]])
        .first()
    )
    if workflow is None:
        raise ValueError(f"Workflow not found for intent {state['intent']!r}.")
    run = models.WorkflowRun(
        workflow_id=workflow.id,
        user_id=user.id,
        instruction=state["instruction"],
        language=state["language"],
        status="RUNNING",
        confidence=None,
        plan={"tools": [{"tool": name, "args": args} for name, args in state["plan"]]},
        started_at=_now(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    state["run_id"] = run.id

    results: list[dict] = []
    failures: list[str] = []
    for index, (tool_name, args) in enumerate(state["plan"]):
        step_started = time.monotonic()
        step_id = _record_step(
            db,
            run.id,
            "data_agent",
            index,
            f"tool:{tool_name}",
            {"tool": tool_name, "args": args},
            None,
            "running",
        )
        try:
            result = tools_registry.execute_tool(db, user, tool_name, args, step_id)
            results.append({"tool": tool_name, "args": args, "result": result})
            step = db.get(models.WorkflowStep, step_id)
            step.status = "success"
            step.output = {"count": result.get("count"), "tool": tool_name}
            step.latency_ms = int((time.monotonic() - step_started) * 1000)
            db.commit()
            state["trace"].append(
                _trace_entry("data_agent", f"tool:{tool_name}", "success", step.latency_ms)
            )
        except Exception as exc:  # noqa: BLE001 - a failed tool must not kill the run
            failures.append(f"{tool_name}: {exc}")
            step = db.get(models.WorkflowStep, step_id)
            step.status = "failed"
            step.output = {"error": str(exc)}
            step.latency_ms = int((time.monotonic() - step_started) * 1000)
            db.commit()
            state["trace"].append(
                _trace_entry(
                    "data_agent", f"tool:{tool_name}", "failed",
                    step.latency_ms, str(exc),
                )
            )
    state["tool_results"] = results
    state["tool_failures"] = failures
    state["trace"].append(
        _trace_entry(
            "data_agent",
            "collect_results",
            "success" if results else "failed",
            int((time.monotonic() - started) * 1000),
            f"{len(results)} tool result(s), {len(failures)} failure(s)",
        )
    )
    return state


def _self_check_node(state: AgentState) -> AgentState:
    started = time.monotonic()
    answer = subagents.build_answer(state["intent"], state["language"], state["tool_results"])
    check = subagents.self_check(state["tool_results"], answer)
    if check["notes"]:
        answer["totals"] = check["corrected_totals"]
        answer["summary"] = subagents.render_summary(
            state["intent"], state["language"], check["corrected_totals"]
        )
    state["answer"] = answer
    state["self_check"] = check
    if state.get("run_id"):
        _record_step(
            state["db"],
            state["run_id"],
            "self_check",
            len(state["trace"]),
            "verify_totals",
            {"totals": answer["totals"]},
            {"passed": check["passed"], "notes": check["notes"]},
            "success" if check["passed"] else "corrected",
            int((time.monotonic() - started) * 1000),
        )
    state["trace"].append(
        _trace_entry(
            "self_check",
            "verify_totals",
            "success" if check["passed"] else "corrected",
            int((time.monotonic() - started) * 1000),
            "; ".join(check["notes"]) if check["notes"] else "totals verified",
        )
    )
    return state


def _finalize_node(state: AgentState) -> AgentState:
    db: Session = state["db"]
    user: models.User = state["user"]
    started = time.monotonic()
    if state["intent"] == "unknown":
        state["answer"] = subagents.build_answer("unknown", state["language"], [])
        state["confidence"] = 0.5
        state["escalated"] = True
        state["status"] = "ESCALATED"
        state["trace"].append(
            _trace_entry(
                "supervisor", "finalize", "escalated",
                int((time.monotonic() - started) * 1000),
                "instruction did not match any known intent",
            )
        )
        audit(
            db,
            user_id=user.id,
            action="INSTRUCT",
            resource="agent/instruct",
            result="ESCALATED",
            details={"intent": "unknown", "parser": state["parser"]},
        )
        return state

    failures = state.get("tool_failures") or []
    if not state.get("tool_results"):
        confidence = 0.0
        status = "FAILED"
    elif failures:
        confidence = 0.7
        status = "COMPLETED"
    elif not state["self_check"]["passed"]:
        confidence = 0.9
        status = "COMPLETED"
    else:
        confidence = 1.0
        status = "COMPLETED"
    escalated = confidence < settings.confidence_threshold
    if escalated and status == "COMPLETED":
        status = "ESCALATED"
    state["confidence"] = confidence
    state["escalated"] = escalated
    state["status"] = status
    run = db.get(models.WorkflowRun, state["run_id"])
    if run is not None:
        run.status = status
        run.confidence = confidence
        run.finished_at = _now()
        db.commit()
    state["trace"].append(
        _trace_entry(
            "supervisor", "finalize", "success",
            int((time.monotonic() - started) * 1000),
            f"status={status} confidence={confidence}",
        )
    )
    audit(
        db,
        user_id=user.id,
        action="INSTRUCT",
        resource="agent/instruct",
        result=status,
        details={
            "intent": state["intent"],
            "parser": state["parser"],
            "tools": [item["tool"] for item in state["tool_results"]],
            "confidence": confidence,
            "run_id": state["run_id"],
        },
    )
    return state


def _route_after_parse(state: AgentState) -> str:
    return "finalize" if state["intent"] == "unknown" else "data_agent"


def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)
    graph.add_node("parse_intent", _parse_intent_node)
    graph.add_node("data_agent", _data_agent_node)
    # Node name must not collide with a state key ("self_check" is one).
    graph.add_node("verify", _self_check_node)
    graph.add_node("finalize", _finalize_node)
    graph.set_entry_point("parse_intent")
    graph.add_conditional_edges("parse_intent", _route_after_parse)
    graph.add_edge("data_agent", "verify")
    graph.add_edge("verify", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


_GRAPH = None


def get_graph() -> StateGraph:
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH


def run_agent(
    db: Session, user: models.User, instruction: str, language: str | None = None
) -> dict:
    """Run one instruction through the supervisor graph and return the
    structured result for the API layer."""
    state: AgentState = {
        "instruction": instruction,
        "language": language or "",
        "user": user,
        "db": db,
        "intent": "unknown",
        "parser": "rule",
        "plan": [],
        "tool_results": [],
        "tool_failures": [],
        "answer": {},
        "self_check": {},
        "confidence": 0.0,
        "escalated": False,
        "run_id": None,
        "status": "RUNNING",
        "trace": [],
    }
    final_state = get_graph().invoke(state)
    answer = final_state.get("answer") or {}
    return {
        "run_id": final_state.get("run_id"),
        "status": final_state.get("status"),
        "intent": final_state.get("intent"),
        "parser": final_state.get("parser"),
        "language": final_state.get("language"),
        "confidence": final_state.get("confidence"),
        "escalated": final_state.get("escalated"),
        "summary": answer.get("summary", ""),
        "rows": answer.get("rows", []),
        "totals": answer.get("totals", {}),
        "tools_used": [item["tool"] for item in final_state.get("tool_results", [])],
        "trace": final_state.get("trace", []),
    }
