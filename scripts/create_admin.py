"""Create the first Admin user — Production (v0.8.0).

Demo accounts are OFF in production, so the first Admin must be
created from the command line. Usage (from the project root):

    AMH_ENV_FILE=.env.production python scripts/create_admin.py \
        --email admin@almadar.local --name "Fahad Ahmad" --role ADMIN

The password is read from --password, from the AMH_ADMIN_PASSWORD
environment variable, or interactively (getpass) — never from a file
in the repo. The same password rules as registration apply
(8+ chars, upper + lower + digit + special). Refuses the three demo
emails unless --force is passed, and refuses a duplicate email.

Requires: local PostgreSQL running with the target database seeded
(or at least migrated — init_db creates the tables).
"""
import argparse
import getpass
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from passlib.context import CryptContext  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402

from app.db import models  # noqa: E402
from app.db.session import SessionLocal, init_db  # noqa: E402

PWD = CryptContext(schemes=["bcrypt"], deprecated="auto")
DEMO_EMAILS = {"admin@almadar.local", "manager@almadar.local", "ops@almadar.local"}
ROLES = {"ADMIN", "OPERATIONS_MANAGER", "OPERATIONS_OFFICER"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SPECIAL = set("!@#$%^&*()-_=+[]{};:,.<>?/")


def validate_password(password: str) -> str | None:
    """Registration password rule (register is 501, so the rule lives
    here): 8+ chars with upper + lower + digit + special. Returns the
    problem, or None when the password is acceptable."""
    if len(password) < 8:
        return "password must be at least 8 characters"
    if not any(c.islower() for c in password):
        return "password must contain a lowercase letter"
    if not any(c.isupper() for c in password):
        return "password must contain an uppercase letter"
    if not any(c.isdigit() for c in password):
        return "password must contain a digit"
    if not any(c in SPECIAL for c in password):
        return "password must contain a special character (!@#$%^&*...)"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a user (first Admin in production).")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--role", default="ADMIN", choices=sorted(ROLES))
    parser.add_argument("--password", default=None, help="If omitted, read from "
                        "AMH_ADMIN_PASSWORD or prompt interactively.")
    parser.add_argument("--force", action="store_true",
                        help="Allow creating one of the demo emails.")
    args = parser.parse_args()

    email = args.email.strip().lower()
    if not EMAIL_RE.match(email):
        print(f"FAIL: '{email}' is not a valid email address.")
        return 1
    if email in DEMO_EMAILS and not args.force:
        print(f"FAIL: '{email}' is a demo account email. Use a real email, "
              "or pass --force if you really mean it.")
        return 1

    import os

    password = args.password or os.environ.get("AMH_ADMIN_PASSWORD")
    if not password:
        password = getpass.getpass("Password: ")
        confirm = getpass.getpass("Password (again): ")
        if password != confirm:
            print("FAIL: passwords do not match.")
            return 1
    problem = validate_password(password)
    if problem:
        print(f"FAIL: {problem}")
        return 1

    init_db()
    db = SessionLocal()
    try:
        if db.query(models.User).filter(models.User.email == email).first():
            print(f"FAIL: a user with email '{email}' already exists.")
            return 1
        user = models.User(
            email=email, name=args.name, role=args.role,
            password_hash=PWD.hash(password),
            created_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.commit()
        print(f"OK: created {args.role} '{email}' (id={user.id}).")
        return 0
    except IntegrityError as exc:
        db.rollback()
        print(f"FAIL: could not create '{email}': {exc.orig}")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
