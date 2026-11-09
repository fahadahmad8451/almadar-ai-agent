"""Logging configuration — Monitoring (v0.9.0).

Application logs go to <data-dir>/logs/app.log through a
RotatingFileHandler (max 5 MB, 5 backups — about 30 MB total). The
data directory is derived from EXPORT_DIR (its parent): data/,
data-staging/ or data-prod/. Old logs are archived by
scripts/rotate_logs.py (see docs/MONITORING.md).

Setup is fail-open: if the log directory cannot be created, logging
stays on the console and the app still starts.
"""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.core.config import settings

MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5


def data_dir() -> Path:
    """The environment's data directory (data/, data-staging/, data-prod/)."""
    return Path(settings.export_dir).parent


def log_dir() -> Path:
    return data_dir() / "logs"


def reports_dir() -> Path:
    return data_dir() / "reports"


def setup_logging() -> Path | None:
    """Attach the rotating file handler to the root logger (and the
    uvicorn loggers, so startup errors land in the file too). Returns
    the log file path, or None when the file handler could not be set
    up. Safe to call twice — a second call is a no-op."""
    directory = log_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        logging.getLogger(__name__).warning(
            "Could not create log directory %s; logging to console only.", directory
        )
        return None
    log_file = directory / "app.log"
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, RotatingFileHandler) and Path(
            getattr(handler, "baseFilename", "")
        ) == log_file:
            return log_file
    handler = RotatingFileHandler(
        log_file, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root.addHandler(handler)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).addHandler(handler)
    if root.level == logging.WARNING:
        root.setLevel(logging.INFO)
    return log_file
