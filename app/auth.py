"""HTTP Basic auth dependency for the admin-only settings area."""
from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from . import config

_security = HTTPBasic()


def require_admin(credentials: HTTPBasicCredentials = Depends(_security)) -> str:
    user_ok = secrets.compare_digest(credentials.username, config.ADMIN_USERNAME)
    pass_ok = secrets.compare_digest(credentials.password, config.ADMIN_PASSWORD)
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid administrator credentials.",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username
