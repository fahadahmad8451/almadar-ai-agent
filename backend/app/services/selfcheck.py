"""Self-check / reflection service — placeholder for Sprint 2.

Before anything reaches a manager, the self-check extracts every
factual claim from the draft (amounts, counts, dates, names), re-queries
the source tools, and compares. Mismatches are corrected once and
re-verified; still-mismatched items are flagged unverified and lower
the confidence score. Tool failures retry with back-off, max 3 attempts.
"""
