"""Run the scripted eval suite from the command line — Sprint 3.

Usage (from the project root):
    python scripts/run_evals.py
Runs the same 12 scenarios as POST /api/v1/eval/run, as the seeded
Admin user, and prints a pass/fail report with the Design section 10
targets. Repeatable: same seed, same expected outputs.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.db.session import SessionLocal
from app.db import models
from app.services import evals as eval_service

TARGETS = {
    "pass_rate": 0.85,
    "tool_accuracy_avg": 0.90,
    "approval_compliance_rate": 1.00,
    "self_check_catch_rate": 0.80,
}


def main() -> int:
    db = SessionLocal()
    try:
        admin = (
            db.query(models.User)
            .filter(models.User.email == "admin@almadar.local")
            .first()
        )
        if admin is None:
            print("Admin user not found — run scripts/seed.py first.")
            return 1
        summary = eval_service.run_eval_suite(db, admin)
        print(f"Eval suite run at {summary['run_at']}")
        print(f"  Passed: {summary['passed']}/{summary['total']} "
              f"(pass rate {summary['pass_rate']:.3f}, target >= {TARGETS['pass_rate']})")
        print(f"  Tool accuracy avg: {summary['tool_accuracy_avg']} (target >= {TARGETS['tool_accuracy_avg']})")
        print(f"  Approval compliance: {summary['approval_compliance_rate']} (target = {TARGETS['approval_compliance_rate']})")
        print(f"  Self-check catch rate: {summary['self_check_catch_rate']} (target >= {TARGETS['self_check_catch_rate']})")
        print(f"  Latency p95: {summary['latency_ms_p95']} ms (target < 60000 ms)")
        for item in summary["results"]:
            mark = "PASS" if item["success"] else "FAIL"
            print(f"  [{mark}] {item['scenario']}")
        return 0 if summary["passed"] == summary["total"] else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
