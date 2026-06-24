"""Token-based session auth for the admin-only area.

The admin page intentionally holds its session token in browser memory only, so
navigating to ``/admin`` always presents a fresh login. A successful login mints
a short-lived bearer token that the admin UI sends with each API request; tokens
are kept in process memory and expire after ``SESSION_TTL`` seconds.
"""
from __future__ import annotations

import secrets
import threading
import time

from fastapi import HTTPException, Request, status

from . import config

# How long a minted admin token stays valid (seconds).
SESSION_TTL = 3600

# Login throttling: at most MAX_FAILURES failed attempts per source address
# within FAILURE_WINDOW seconds before further attempts are rejected.
MAX_FAILURES = 5
FAILURE_WINDOW = 300

_lock = threading.Lock()
_sessions: dict[str, float] = {}
_failures: dict[str, list[float]] = {}


def verify_credentials(username: str, password: str) -> bool:
    user_ok = secrets.compare_digest(username, config.ADMIN_USERNAME)
    pass_ok = secrets.compare_digest(password, config.ADMIN_PASSWORD)
    return user_ok and pass_ok


def create_session() -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _lock:
        # Opportunistically drop expired tokens so the store doesn't grow.
        expired = [key for key, expiry in _sessions.items() if expiry < now]
        for key in expired:
            del _sessions[key]
        _sessions[token] = now + SESSION_TTL
    return token


def destroy_session(token: str) -> None:
    with _lock:
        _sessions.pop(token, None)


def check_rate_limit(ip: str) -> None:
    """Raise 429 when ``ip`` has exceeded the failed-login allowance."""
    now = time.time()
    with _lock:
        attempts = [t for t in _failures.get(ip, []) if now - t < FAILURE_WINDOW]
        _failures[ip] = attempts
        if len(attempts) >= MAX_FAILURES:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many failed attempts. Please wait and try again.",
            )


def record_failure(ip: str) -> None:
    now = time.time()
    with _lock:
        _failures.setdefault(ip, []).append(now)


def reset_failures(ip: str) -> None:
    with _lock:
        _failures.pop(ip, None)


def _extract_token(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[7:]
    # Allow a query-string token so <img> tags can load protected images.
    return request.query_params.get("token", "")


def require_admin(request: Request) -> str:
    """FastAPI dependency: validate the bearer token on admin requests."""
    token = _extract_token(request)
    now = time.time()
    with _lock:
        expiry = _sessions.get(token)
        if expiry is None or expiry < now:
            _sessions.pop(token, None)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required.",
            )
    return token
