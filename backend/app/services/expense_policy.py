"""Expense policy rules — Sprint 2.

Demo defaults locked in the design (Fahad approved 2026-11-06,
changeable): per-category limits and the second-approval threshold.
The Report Agent re-checks every pending claim against these rules;
the seeded claims already carry the matching policy flags.
"""
from app.db import models

# Per-category claim limits in SAR (demo defaults, changeable).
CATEGORY_LIMITS_SAR: dict[str, float] = {
    "travel": 5000.0,
    "meals": 300.0,
    "office supplies": 2000.0,
    "training": 3000.0,
    "other": 1000.0,
}

# Above this amount a second approval is required (Operations Manager + Admin).
SECOND_APPROVAL_THRESHOLD_SAR = 10000.0


def category_limit(category: str) -> float:
    """Limit for a category (case-insensitive); unknown categories use
    the 'other' limit."""
    return CATEGORY_LIMITS_SAR.get((category or "").strip().lower(), CATEGORY_LIMITS_SAR["other"])


def check_claim(claim: models.ExpenseClaim) -> list[str]:
    """Policy flags for one claim, computed from the live rules. An
    empty list means the claim is clean."""
    flags: list[str] = []
    if not claim.receipt_attached:
        flags.append("Missing receipt")
    limit = category_limit(claim.category)
    if claim.amount_sar > limit:
        flags.append(
            f"Over category limit ({limit:,.0f} SAR)"
        )
    if claim.amount_sar > SECOND_APPROVAL_THRESHOLD_SAR:
        flags.append(
            f"Second approval required (over {SECOND_APPROVAL_THRESHOLD_SAR:,.0f} SAR)"
        )
    return flags
