"""Back up the production database and data directories.

Usage (from the project root):

    AMH_ENV_FILE=.env.production python scripts/backup.py [--out backups]

Creates backups/<timestamp>/ containing:
    db.dump      — pg_dump custom-format dump of the database
    data-prod/   — copy of the exports / uploads / evals directories
    manifest.json — version, database, timestamp, row counts

The database password comes from the configured database URL
(AMH_DATABASE_URL in the env file); pg_dump is given it through the
PGPASSWORD environment variable, never on the command line.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.config import settings  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data-prod"


def _pg_env(url: str) -> tuple[dict, dict]:
    parsed = urlparse(url)
    if parsed.scheme not in ("postgresql", "postgresql+psycopg2", "postgresql+psycopg"):
        raise ValueError(f"Unsupported database URL scheme: {parsed.scheme}")
    env = dict(os.environ)
    if parsed.password:
        env["PGPASSWORD"] = parsed.password
    conn = {
        "host": parsed.hostname or "127.0.0.1",
        "port": str(parsed.port or 5432),
        "user": parsed.username or "postgres",
        "dbname": parsed.path.lstrip("/"),
    }
    return env, conn


def _counts() -> dict:
    from sqlalchemy import text

    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        tables = ["users", "erp_invoices", "workflow_runs", "approvals",
                  "report_exports", "scheduled_jobs", "eval_results", "audit_logs"]
        out = {}
        for table in tables:
            out[table] = db.execute(text(f"SELECT count(*) FROM {table}")).scalar()
        return out
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Back up the database and data dirs.")
    parser.add_argument("--out", default="backups", help="Backups root directory.")
    args = parser.parse_args()

    env, conn = _pg_env(settings.database_url)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = Path(args.out).resolve() / stamp
    dest.mkdir(parents=True)
    print(f"Backing up database '{conn['dbname']}' → {dest}")

    dump_path = dest / "db.dump"
    result = subprocess.run(
        ["pg_dump", "-h", conn["host"], "-p", conn["port"], "-U", conn["user"],
         "-d", conn["dbname"], "-F", "c", "-f", str(dump_path)],
        env=env, capture_output=True, text=True,
    )
    if result.returncode != 0 or not dump_path.exists() or dump_path.stat().st_size == 0:
        print(f"FAIL: pg_dump failed: {result.stderr.strip()}")
        shutil.rmtree(dest, ignore_errors=True)
        return 1

    data_copied = {}
    if DATA_DIR.exists():
        for sub in ("exports", "uploads", "evals"):
            src = DATA_DIR / sub
            if src.exists():
                shutil.copytree(src, dest / "data-prod" / sub)
                data_copied[sub] = sum(1 for _ in (dest / "data-prod" / sub).rglob("*") if _.is_file())

    manifest = {
        "version": settings.version,
        "environment": settings.environment,
        "database": conn["dbname"],
        "created_at_utc": stamp,
        "db_dump_bytes": dump_path.stat().st_size,
        "data_files": data_copied,
        "row_counts": _counts(),
    }
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"OK: backup complete — {dest}")
    print(f"    db.dump: {manifest['db_dump_bytes']:,} bytes; "
          f"data files: {sum(data_copied.values())}; rows: {manifest['row_counts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
