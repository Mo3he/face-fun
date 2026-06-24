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

_lock = threading.Lock()
_sessions: dict[str, float] = {}


def verify_credentials(username: str, password: str) -> bool:
    user_ok = secrets.compare_digest(username, config.ADMIN_USERNAME)
    pass_ok = secrets.compare_digest(password, config.ADMIN_PASSWORD)
    return user_ok and pass_ok


def create_session() -> str:
    token = secrets.token_urlsafe(32)
    with _lock:
        _sessions[token] = time.time() + SESSION_TTL
    return token


def destroy_session(token: str) -> None:
    with _lock:
        _sessions.pop(token, None)


def require_admin(request: Request) -> str:
    """FastAPI dependency: validate the bearer token on admin API requests."""
    header = request.headers.get("Authorization", "")
    token = header[7:] if header.startswith("Bearer ") else ""
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
