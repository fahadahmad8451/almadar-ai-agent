"""FastAPI entrypoint — Al Madar Holding Enterprise AI Agent.

Setup v0.1, NO Docker required. Runs on plain Windows:
    python -m venv .venv
    .venv\\Scripts\\activate
    pip install -r backend\\requirements.txt
    uvicorn app.main:app --port 8100

Real, working in v0.4: GET /health and GET /api/v1/health — including a
real PostgreSQL connection check. The database is created at startup
(lifespan calls init_db()); if PostgreSQL is unreachable the app still
starts but /health honestly reports "database": "unavailable: ...".
There is no in-memory / SQLite fallback.
Auth, agent runs, workflows, approvals, reports, schedules, admin,
eval and invoice upload are live (Sprints 1–3); the scheduler starts
in the lifespan (fail-open — a scheduler failure never stops the app).
Endpoints not built yet return an honest 501 — never a fake success.
"""
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import admin, agent, approvals, auth, dashboard, eval, invoices, reports, schedules, webhooks, workflows
from app.core.config import settings, validate_production_settings
from app.core.logging_config import setup_logging
from app.core.security import role_from_request
from app.db import session as db_session
from app.db.session import init_db
from app.services import monitoring as monitoring_service
from app.services import scheduler as scheduler_service

logger = logging.getLogger(__name__)
STARTED_AT = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Production refuses to start half-secured (weak JWT secret,
    # wildcard CORS). The check raises before any request is served.
    validate_production_settings()
    # Monitoring (v0.9.0): rotating file log (5 MB, 5 backups) in
    # <data-dir>/logs/app.log. Fail-open — logging never stops startup.
    log_file = setup_logging()
    init_db()
    logger.info("Startup complete. Database: %s", db_session.DB_STATUS)
    if log_file is not None:
        logger.info("Application log: %s", log_file)
    # Fail-open: the scheduler must never stop the app from serving.
    # Staging runs with scheduler_enabled=false (jobs stay visible and
    # manual-only); dev/production start it normally.
    if settings.scheduler_enabled:
        scheduler_service.start_scheduler()
    else:
        logger.info("Scheduler disabled by settings (scheduler_enabled=false).")
    yield
    scheduler_service.shutdown_scheduler()


def envelope(data: dict, request_id: str) -> dict:
    return {"success": True, "data": data, "error": None, "request_id": request_id}


def health_payload() -> dict:
    return {
        "status": "ok",
        "version": settings.version,
        "service": settings.service,
        "environment": settings.environment,
        "database": db_session.DB_STATUS,
        "demo_accounts_enabled": settings.demo_accounts_enabled,
        "uptime_seconds": round(time.time() - STARTED_AT, 1),
    }


app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = str(uuid.uuid4())
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    # Monitoring (v0.9.0): record every request (endpoint, method,
    # status, latency, caller role) into request_metrics. Fail-open —
    # a metrics failure is logged inside the service and never breaks
    # the response. The metrics endpoint itself is recorded too, so
    # the counts are honest about all traffic.
    try:
        monitoring_service.record_request_metric(
            endpoint=request.url.path,
            method=request.method,
            status=response.status_code,
            latency_ms=int((time.perf_counter() - started) * 1000),
            role=role_from_request(request),
        )
    except Exception:  # noqa: BLE001 - metrics must never break serving
        logger.warning("Request metric recording failed.", exc_info=True)
    # Production hardening (v0.8.0): security headers on every response.
    # The Server header is not set here — uvicorn adds it, so the
    # production start script runs uvicorn with --no-server-header.
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; font-src 'self'; connect-src 'self'"
    )
    return response


_HTTP_ERROR_CODES = {401: "unauthorized", 403: "forbidden", 404: "not_found", 429: "rate_limited"}


async def _not_found_default(scope, receive, send):
    # Unmatched routes bypass exception handlers (Router.not_found
    # returns {"detail": "Not Found"} directly), so the router's
    # default is overridden to keep the envelope everywhere.
    response = JSONResponse(
        status_code=404,
        content={
            "success": False,
            "data": None,
            "error": {"code": "not_found", "message": "Route not found."},
            "request_id": "",
        },
    )
    await response(scope, receive, send)


app.router.default = _not_found_default


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    # HTTPExceptions (401/403/404/429 from auth, RBAC and validation) use
    # the same envelope as every other response — never {"detail": ...}.
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "data": None,
            "error": {
                "code": _HTTP_ERROR_CODES.get(exc.status_code, f"http_{exc.status_code}"),
                "message": str(exc.detail),
            },
            "request_id": request.headers.get("X-Request-Id", ""),
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "data": None,
            "error": {"code": "internal_error", "message": "Internal server error."},
            "request_id": request.headers.get("X-Request-Id", ""),
        },
    )


@app.get("/health")
def health_root():
    return envelope(health_payload(), str(uuid.uuid4()))


@app.get("/api/v1/health")
def health_v1():
    return envelope(health_payload(), str(uuid.uuid4()))


app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(agent.router, prefix="/api/v1/agent", tags=["agent"])
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["dashboard"])
app.include_router(workflows.router, prefix="/api/v1/workflows", tags=["workflows"])
app.include_router(approvals.router, prefix="/api/v1/approvals", tags=["approvals"])
app.include_router(reports.router, prefix="/api/v1", tags=["reports"])
app.include_router(invoices.router, prefix="/api/v1/invoices", tags=["invoices"])
app.include_router(webhooks.router, prefix="/api/v1/webhooks", tags=["webhooks"])
app.include_router(schedules.router, prefix="/api/v1/schedules", tags=["schedules"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])
app.include_router(eval.router, prefix="/api/v1/eval", tags=["eval"])
