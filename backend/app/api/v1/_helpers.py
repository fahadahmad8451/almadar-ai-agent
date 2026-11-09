"""Shared helper for honest 501 responses.

Setup v0.1: every endpoint that is not built yet returns 501 with the
same response envelope as the rest of the API — never a fake success.
"""
import uuid

from fastapi.responses import JSONResponse


def ok(data, status_code: int = 200) -> JSONResponse:
    """Success envelope — same shape as the rest of the API."""
    return JSONResponse(
        status_code=status_code,
        content={
            "success": True,
            "data": data,
            "error": None,
            "request_id": str(uuid.uuid4()),
        },
    )


def fail(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "data": None,
            "error": {"code": code, "message": message},
            "request_id": str(uuid.uuid4()),
        },
    )


def not_implemented(feature: str) -> JSONResponse:
    return JSONResponse(
        status_code=501,
        content={
            "success": False,
            "data": None,
            "error": {
                "code": "not_implemented",
                "message": f"{feature} is not implemented yet.",
            },
            "request_id": str(uuid.uuid4()),
        },
    )
