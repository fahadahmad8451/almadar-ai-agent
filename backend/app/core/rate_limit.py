"""In-memory login rate limiting — Production (v0.8.0).

Same rule as Project 1 v0.8: 5 FAILED login attempts per 60 seconds
per (client IP, email) → 429 with a Retry-After header. Only failures
count; a successful login clears the counter. The limiter is
in-memory and per-process — production runs a single uvicorn worker,
so the limit holds. Do not run with --workers > 1 (no shared store).
"""
import threading
import time

MAX_FAILED_LOGINS = 5
WINDOW_SECONDS = 60

_lock = threading.Lock()
_failures: dict[tuple[str, str], list[float]] = {}


def _prune(key: tuple[str, str], now: float) -> list[float]:
    kept = [t for t in _failures.get(key, []) if now - t < WINDOW_SECONDS]
    if kept:
        _failures[key] = kept
    else:
        _failures.pop(key, None)
    return kept


def login_blocked_seconds(ip: str, email: str) -> int | None:
    """Seconds to wait before the next login attempt, or None."""
    key = (ip or "unknown", (email or "").strip().lower())
    now = time.monotonic()
    with _lock:
        attempts = _prune(key, now)
        if len(attempts) < MAX_FAILED_LOGINS:
            return None
        oldest = min(attempts)
        return max(1, int(WINDOW_SECONDS - (now - oldest)) + 1)


def record_login_failure(ip: str, email: str) -> None:
    key = (ip or "unknown", (email or "").strip().lower())
    now = time.monotonic()
    with _lock:
        attempts = _prune(key, now)
        attempts.append(now)
        _failures[key] = attempts


def clear_login_failures(ip: str, email: str) -> None:
    key = (ip or "unknown", (email or "").strip().lower())
    with _lock:
        _failures.pop(key, None)


def reset_login_limits() -> None:
    """Test helper — clear every counter."""
    with _lock:
        _failures.clear()
