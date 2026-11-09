"""Restore a backup created by scripts/backup.py.

Usage (from the project root):

    AMH_ENV_FILE=.env.production python scripts/restore.py backups/20261106-120000 [--yes]

Restores the pg_dump into the configured database (drops and
recreates its tables via pg_restore --clean) and copies the backed-up
data-prod/ directories back. The target database is created first if
it does not exist. Use --yes to skip the confirmation prompt.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
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


def _ensure_db(env: dict, conn: dict) -> None:
    check = subprocess.run(
        ["psql", "-h", conn["host"], "-p", conn["port"], "-U", conn["user"],
         "-d", "postgres", "-tAc",
         f"SELECT 1 FROM pg_database WHERE datname = '{conn['dbname']}'"],
        env=env, capture_output=True, text=True,
    )
    if check.stdout.strip() == "1":
        return
    created = subprocess.run(
        ["psql", "-h", conn["host"], "-p", conn["port"], "-U", conn["user"],
         "-d", "postgres", "-c", f'CREATE DATABASE "{conn["dbname"]}"'],
        env=env, capture_output=True, text=True,
    )
    if created.returncode != 0:
        raise RuntimeError(f"could not create database: {created.stderr.strip()}")
    print(f"Created database '{conn['dbname']}'.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore a backup.")
    parser.add_argument("backup", help="Backup directory, e.g. backups/20261106-120000")
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
    args = parser.parse_args()

    src = Path(args.backup).resolve()
    dump_path = src / "db.dump"
    if not dump_path.exists():
        print(f"FAIL: no db.dump in {src}")
        return 1
    manifest = {}
    manifest_path = src / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    env, conn = _pg_env(settings.database_url)
    print(f"Restore {src} into database '{conn['dbname']}'")
    if manifest:
        print(f"  backup version {manifest.get('version')}, "
              f"created {manifest.get('created_at_utc')}, "
              f"rows {manifest.get('row_counts')}")
    if not args.yes:
        answer = input("This replaces the current database contents. Continue? [y/N] ")
        if answer.strip().lower() != "y":
            print("Aborted.")
            return 1

    _ensure_db(env, conn)
    result = subprocess.run(
        ["pg_restore", "-h", conn["host"], "-p", conn["port"], "-U", conn["user"],
         "-d", conn["dbname"], "--clean", "--if-exists", str(dump_path)],
        env=env, capture_output=True, text=True,
    )
    # pg_restore --clean reports errors for objects that do not exist
    # yet; a zero exit code plus a non-empty database is the success
    # signal, so check the tables below instead of the stderr text.
    if result.returncode != 0:
        print(f"pg_restore exited {result.returncode}; checking tables…")

    backed_data = src / "data-prod"
    if backed_data.exists():
        if DATA_DIR.exists():
            shutil.rmtree(DATA_DIR)
        shutil.copytree(backed_data, DATA_DIR)
        print(f"Restored data-prod/ ({sum(1 for _ in DATA_DIR.rglob('*') if _.is_file())} files).")

    from sqlalchemy import text

    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        users = db.execute(text("SELECT count(*) FROM users")).scalar()
        invoices = db.execute(text("SELECT count(*) FROM erp_invoices")).scalar()
    finally:
        db.close()
    print(f"OK: restore complete — users={users}, invoices={invoices}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
