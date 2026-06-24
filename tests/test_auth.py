"""Tests for admin session-token auth (needs fastapi)."""
import pytest

pytest.importorskip("fastapi")

from fastapi import HTTPException  # noqa: E402

from app import auth, config  # noqa: E402


class _FakeRequest:
    """Minimal stand-in exposing the bits ``require_admin`` reads."""

    def __init__(self, headers=None, query=None):
        self.headers = headers or {}
        self.query_params = query or {}


def test_verify_credentials():
    assert auth.verify_credentials(config.ADMIN_USERNAME, config.ADMIN_PASSWORD)
    assert not auth.verify_credentials("nope", "wrong")


def test_session_lifecycle():
    token = auth.create_session()
    req = _FakeRequest(headers={"Authorization": f"Bearer {token}"})
    assert auth.require_admin(req) == token

    auth.destroy_session(token)
    with pytest.raises(HTTPException):
        auth.require_admin(req)


def test_token_via_query_param():
    token = auth.create_session()
    req = _FakeRequest(query={"token": token})
    assert auth.require_admin(req) == token


def test_missing_token_rejected():
    with pytest.raises(HTTPException):
        auth.require_admin(_FakeRequest())


def test_expired_token_purged():
    import time

    token = auth.create_session()
    # Force the stored expiry into the past.
    auth._sessions[token] = time.time() - 1
    with pytest.raises(HTTPException):
        auth.require_admin(_FakeRequest(headers={"Authorization": f"Bearer {token}"}))
    assert token not in auth._sessions


def test_rate_limit():
    ip = "203.0.113.7"
    auth.reset_failures(ip)
    for _ in range(auth.MAX_FAILURES):
        auth.check_rate_limit(ip)  # under the cap, allowed
        auth.record_failure(ip)
    with pytest.raises(HTTPException):
        auth.check_rate_limit(ip)
    # Resetting clears the throttle.
    auth.reset_failures(ip)
    auth.check_rate_limit(ip)
