"""Log rotation / archiving — v0.9.0.

The live log (logs/app.log) is rotated by the application itself
(RotatingFileHandler: 5 MB, 5 backups — see
app/core/logging_config.py). This script handles the rest:

- Rotated backups (app.log.1 … app.log.5) older than 7 days are
  compressed into logs/archives/app-YYYYMMDD-HHMMSS.log.gz.
- Archives older than 30 days are deleted.
- Nothing is ever deleted before it is archived.

Usage:
    AMH_ENV_FILE=.env.production python scripts/rotate_logs.py [--days 7] [--keep-days 30]
    python scripts/rotate_logs.py --log-dir data/logs   # explicit directory (tests)

Run weekly (cron / Task Scheduler — see docs/MONITORING.md).
"""
import argparse
import gzip
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def rotate(log_dir: Path, archive_after_days: int = 7, keep_days: int = 30) -> dict:
    now = datetime.now()
    archives_dir = log_dir / "archives"
    archives_dir.mkdir(parents=True, exist_ok=True)
    archived = 0
    deleted = 0
    for path in sorted(log_dir.glob("app.log.*")):
        if path.is_dir() or path.suffix == ".gz":
            continue
        age = now - datetime.fromtimestamp(path.stat().st_mtime)
        if age < timedelta(days=archive_after_days):
            continue
        stamp = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y%m%d-%H%M%S")
        target = archives_dir / f"app-{stamp}.log.gz"
        with path.open("rb") as source, gzip.open(target, "wb") as dest:
            shutil.copyfileobj(source, dest)
        path.unlink()
        archived += 1
    for path in sorted(archives_dir.glob("*.gz")):
        age = now - datetime.fromtimestamp(path.stat().st_mtime)
        if age > timedelta(days=keep_days):
            path.unlink()
            deleted += 1
    return {"archived": archived, "deleted": deleted, "archives_dir": str(archives_dir)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive old rotated logs.")
    parser.add_argument("--log-dir", default=None)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--keep-days", type=int, default=30)
    args = parser.parse_args()
    if args.log_dir:
        log_dir = Path(args.log_dir)
    else:
        from app.core.logging_config import log_dir as _log_dir

        log_dir = _log_dir()
    result = rotate(log_dir, archive_after_days=args.days, keep_days=args.keep_days)
    print(
        f"Log rotation: archived {result['archived']} file(s), "
        f"deleted {result['deleted']} old archive(s) in {result['archives_dir']}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
