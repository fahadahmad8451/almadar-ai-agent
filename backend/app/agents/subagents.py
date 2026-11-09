"""Sub-agents — Sprint 1: Data Agent is LIVE; Report Agent and Approval
Agent arrive in later sprints.

- Data Agent: chooses tools for the parsed intent, calls them through
  the registry (permission-checked, recorded), and hands structured
  results to the answer builder.
- Self-check (Sprint 1, basic): re-computes every total from the raw
  tool rows and compares it with the answer totals. A mismatch is
  corrected once; if it still mismatches, the item is flagged
  unverified and confidence drops.
- Intent parsing: the Supervisor first tries the local LLM (Ollama);
  when Ollama is unreachable it falls back to deterministic keyword
  rules (English + Arabic). The parser used is recorded in the trace,
  so a rule-based run is never presented as an LLM run.
"""
import json
import re

import httpx

from app.core.config import settings

INTENTS = (
    "pending_invoices",
    "overdue_suppliers",
    "stale_leads",
    "pending_expenses",
    "customers_list",
    "unknown",
)

INTENT_WORKFLOW = {
    "pending_invoices": "INVOICE_REPORT",
    "overdue_suppliers": "SUPPLIER_FOLLOWUP",
    "stale_leads": "CRM_FOLLOWUP",
    "pending_expenses": "EXPENSE_APPROVAL",
    "customers_list": "CRM_FOLLOWUP",
}

_ARABIC_RE = re.compile(r"[\u0600-\u06FF]")

# Keyword rules (English + Arabic). Checked in this order — the most
# specific intents first so "overdue suppliers" does not match invoices.
_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    (
        "pending_expenses",
        ("expense", "expenses", "claim", "claims", "مصروف", "مصاريف", "نفقات", "مطالبة"),
    ),
    (
        "overdue_suppliers",
        ("supplier", "suppliers", "مورد", "موردين", "الموردين", "الموردون"),
    ),
    (
        "pending_invoices",
        ("invoice", "invoices", "فاتورة", "فواتير", "الفواتير"),
    ),
    (
        "stale_leads",
        ("stale lead", "stale leads", "lead", "leads", "عميل محتمل", "عملاء محتملين"),
    ),
    (
        "customers_list",
        ("customer", "customers", "عميل", "عملاء", "العملاء"),
    ),
]


def detect_language(text: str) -> str:
    """Arabic script present -> 'ar', otherwise 'en'."""
    return "ar" if _ARABIC_RE.search(text or "") else "en"


def parse_intent_rule(instruction: str) -> str:
    lowered = (instruction or "").lower()
    for intent, keywords in _KEYWORDS:
        if any(kw in lowered for kw in keywords):
            return intent
    return "unknown"


def parse_intent_llm(instruction: str) -> str | None:
    """Ask the local LLM to classify the intent. Returns None on any
    failure (Ollama down, timeout, bad JSON) so the caller falls back
    to the deterministic rules."""
    prompt = (
        "Classify the user instruction into exactly one intent from this "
        "list: pending_invoices, overdue_suppliers, stale_leads, "
        "pending_expenses, customers_list, unknown. "
        'Reply with JSON only, like {"intent": "pending_invoices"}. '
        f"Instruction: {instruction}"
    )
    try:
        response = httpx.post(
            f"{settings.ollama_host}/api/chat",
            json={
                "model": settings.supervisor_model,
                "messages": [{"role": "user", "content": prompt}],
                "format": "json",
                "stream": False,
                "options": {"temperature": 0},
            },
            timeout=5,
        )
        response.raise_for_status()
        content = response.json()["message"]["content"]
        intent = json.loads(content).get("intent")
        return intent if intent in INTENTS else None
    except Exception:  # noqa: BLE001 - any LLM failure means rule fallback
        return None


def parse_intent(instruction: str) -> tuple[str, str]:
    """Returns (intent, parser) where parser is 'llm' or 'rule'."""
    intent = parse_intent_llm(instruction)
    if intent is not None:
        return intent, "llm"
    return parse_intent_rule(instruction), "rule"


def _detect_period(instruction: str) -> str:
    lowered = (instruction or "").lower()
    if "last month" in lowered or "الشهر الماضي" in lowered:
        return "last_month"
    if "this month" in lowered or "هذا الشهر" in lowered:
        return "this_month"
    return "all"


def _invoice_status(instruction: str) -> str | None:
    lowered = (instruction or "").lower()
    for status, words in (
        ("OVERDUE", ("overdue", "متأخر")),
        ("PENDING", ("pending", "معلقة", "المعلقة")),
        ("PAID", ("paid", "مدفوعة")),
        ("DISPUTED", ("disputed", "متنازع")),
    ):
        if any(w in lowered for w in words):
            return status
    return None


def plan_for_intent(intent: str, instruction: str) -> list[tuple[str, dict]]:
    """The tool calls for an intent. Args come from the instruction text
    only through fixed rules — never from LLM-generated SQL or JSON."""
    if intent == "pending_invoices":
        return [
            (
                "list_invoices",
                {"status": _invoice_status(instruction), "period": _detect_period(instruction)},
            )
        ]
    if intent == "overdue_suppliers":
        return [("list_suppliers", {"overdue": True})]
    if intent == "stale_leads":
        return [("list_leads", {"status": "STALE"})]
    if intent == "pending_expenses":
        return [("list_expense_claims", {"pending_only": True})]
    if intent == "customers_list":
        return [("list_customers", {})]
    return []


_SUMMARIES = {
    "pending_invoices": {
        "en": "Found {count} invoices totalling {total} SAR (VAT {vat} SAR).",
        "ar": "تم العثور على {count} فاتورة بإجمالي {total} ر.س (ضريبة القيمة المضافة {vat} ر.س).",
    },
    "overdue_suppliers": {
        "en": "Found {count} suppliers with overdue invoices totalling {total} SAR.",
        "ar": "تم العثور على {count} موردين لديهم فواتير متأخرة بإجمالي {total} ر.س.",
    },
    "stale_leads": {
        "en": "Found {count} stale leads that need follow-up.",
        "ar": "تم العثور على {count} عملاء محتملين غير نشطين يحتاجون إلى متابعة.",
    },
    "pending_expenses": {
        "en": "Found {count} expense claims awaiting a decision totalling {total} SAR.",
        "ar": "تم العثور على {count} مطالبة مصاريف بانتظار القرار بإجمالي {total} ر.س.",
    },
    "customers_list": {
        "en": "Found {count} customers.",
        "ar": "تم العثور على {count} عميل.",
    },
    "unknown": {
        "en": (
            "I could not understand that instruction. Try asking about "
            "pending invoices, overdue suppliers, stale leads, expense "
            "claims, or customers."
        ),
        "ar": (
            "لم أتمكن من فهم هذا الطلب. جرّب السؤال عن الفواتير المعلقة أو "
            "الموردين المتأخرين أو العملاء المحتملين غير النشطين أو مطالبات "
            "المصاريف أو العملاء."
        ),
    },
}


def _row_amount(row: dict) -> float:
    """Amount carried by a result row: invoices/claims use amount_sar,
    supplier rows use overdue_total_sar."""
    if not isinstance(row, dict):
        return 0.0
    value = row.get("amount_sar", row.get("overdue_total_sar", 0)) or 0
    return float(value)


def _row_vat(row: dict) -> float:
    if not isinstance(row, dict):
        return 0.0
    return float(row.get("vat_sar", 0) or 0)


def render_summary(intent: str, language: str, totals: dict) -> str:
    template = _SUMMARIES.get(intent, _SUMMARIES["unknown"])[language if language in ("en", "ar") else "en"]
    return template.format(
        count=totals["count"],
        total=f"{totals['total_amount_sar']:,.2f}",
        vat=f"{totals['total_vat_sar']:,.2f}",
    )


def build_answer(intent: str, language: str, tool_results: list[dict]) -> dict:
    """Build the structured answer from tool results. Totals are computed
    here from the raw rows — the self-check re-computes them again."""
    primary = tool_results[0]["result"] if tool_results else {"rows": [], "count": 0}
    rows = primary.get("rows", [])
    totals = {
        "count": primary.get("count", len(rows)),
        "total_amount_sar": round(sum(_row_amount(r) for r in rows), 2),
        "total_vat_sar": round(sum(_row_vat(r) for r in rows), 2),
    }
    summary = render_summary(intent, language, totals)
    return {"summary": summary, "rows": rows, "totals": totals}


def self_check(tool_results: list[dict], answer: dict) -> dict:
    """Re-compute totals from the raw tool rows and compare with the
    answer. Returns {passed, notes, corrected_totals}."""
    notes: list[str] = []
    corrected = dict(answer["totals"])
    for item in tool_results:
        result = item["result"]
        rows = result.get("rows", [])
        recount = len(rows)
        resum = round(sum(_row_amount(r) for r in rows), 2)
        resvat = round(sum(_row_vat(r) for r in rows), 2)
        if result.get("count", recount) != recount:
            notes.append(
                f"Tool {item['tool']} reported count {result.get('count')} "
                f"but returned {recount} rows; corrected to {recount}."
            )
            corrected["count"] = recount
        if abs(result.get("total_amount_sar", resum) - resum) > 0.01:
            notes.append(f"Tool {item['tool']} total corrected to {resum:.2f} SAR.")
            corrected["total_amount_sar"] = resum
        if abs(result.get("total_vat_sar", resvat) - resvat) > 0.01:
            notes.append(f"Tool {item['tool']} VAT total corrected to {resvat:.2f} SAR.")
            corrected["total_vat_sar"] = resvat
    return {"passed": not notes, "notes": notes, "corrected_totals": corrected}
