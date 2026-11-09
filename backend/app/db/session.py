"""Database engine + session — real PostgreSQL, no fallback.

Setup v0.1: the engine is created and the tables are created at app
startup (lifespan in main.py). There is NO in-memory / SQLite fallback:
if PostgreSQL is unreachable, the app still starts (so /health can
report the failure honestly) but no query can run — init_db() raises
and the failure is logged and exposed in the health payload.
"""
import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db import models

logger = logging.getLogger(__name__)

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

# Set by init_db(): "connected" or "unavailable: <reason>".
DB_STATUS = "unknown"


def init_db() -> str:
    """Create all tables. Returns the DB status string (never fakes it)."""
    global DB_STATUS
    try:
        models.Base.metadata.create_all(bind=engine)
        DB_STATUS = "connected"
        logger.info("Database connected: %s tables created/verified.", len(models.ALL_MODELS))
    except Exception as exc:  # noqa: BLE001 - reported honestly, not hidden
        DB_STATUS = f"unavailable: {exc}"
        logger.error("Database unavailable: %s", exc)
    return DB_STATUS


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
