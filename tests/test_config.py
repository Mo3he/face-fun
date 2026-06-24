"""Tests for the persisted settings layer (stdlib only)."""
from app.config import Settings


def test_defaults_present():
    s = Settings()
    values = s.all()
    assert "rtsp_url" in values
    assert "max_captures" in values
    assert "max_photos" in values


def test_update_persists_and_coerces():
    s = Settings()
    s.update({"smtp_host": "smtp.example.com", "smtp_port": "465"})
    assert s.get("smtp_host") == "smtp.example.com"
    # Port arrives as a string from the form but is coerced to int.
    assert s.get("smtp_port") == 465


def test_bool_coercion():
    s = Settings()
    s.update({"smtp_use_tls": "no"})
    assert s.get("smtp_use_tls") is False
    s.update({"smtp_use_tls": "yes"})
    assert s.get("smtp_use_tls") is True


def test_unknown_keys_ignored():
    s = Settings()
    s.update({"not_a_setting": "x"})
    assert s.get("not_a_setting") is None


def test_secret_masked_in_public():
    s = Settings()
    s.update({"smtp_password": "hunter2"})
    pub = s.public()
    assert pub["smtp_password"] == "********"
    # The real value is still readable internally.
    assert s.get("smtp_password") == "hunter2"


def test_masked_secret_not_overwritten():
    s = Settings()
    s.update({"smtp_password": "real-secret"})
    # Re-submitting the masked placeholder must not clobber the stored value.
    s.update({"smtp_password": "********"})
    assert s.get("smtp_password") == "real-secret"
