"""Application configuration and persisted, admin-editable settings.

Admin credentials come from environment variables only (never editable from the
UI). Operational settings (RTSP URL, SMTP details, recognition tuning) are stored
in a JSON file inside the data directory so they survive container restarts and
can be edited from the locked admin tab.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
PHOTOS_DIR = DATA_DIR / "photos"
# Auto-saved cropped images of faces as they are detected on the stream.
CAPTURES_DIR = DATA_DIR / "captures"
# Thumbnail crops saved when a face is enrolled.
FACES_DIR = DATA_DIR / "faces"
SETTINGS_FILE = DATA_DIR / "settings.json"
DB_FILE = DATA_DIR / "facefun.db"

# Admin credentials (environment only).
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")

# Default operational settings. Environment variables provide the initial value
# the first time the app runs; afterwards the JSON file is the source of truth.
DEFAULT_SETTINGS: dict[str, Any] = {
    "rtsp_url": os.environ.get("RTSP_URL", ""),
    "smtp_host": os.environ.get("SMTP_HOST", ""),
    "smtp_port": int(os.environ.get("SMTP_PORT", "587")),
    "smtp_user": os.environ.get("SMTP_USER", ""),
    "smtp_password": os.environ.get("SMTP_PASSWORD", ""),
    "smtp_use_tls": os.environ.get("SMTP_USE_TLS", "true").lower() == "true",
    "smtp_from": os.environ.get("SMTP_FROM", ""),
    # face_recognition distance threshold. Lower = stricter match. 0.6 is the
    # library default; raising it makes recognition more forgiving of props.
    "recognition_tolerance": float(os.environ.get("RECOGNITION_TOLERANCE", "0.6")),
    # Run recognition every N captured frames to keep CPU usage reasonable.
    "detect_every": int(os.environ.get("DETECT_EVERY", "5")),
    # Retention caps (0 = keep everything). Oldest items are pruned past these.
    "max_captures": int(os.environ.get("MAX_CAPTURES", "500")),
    "max_photos": int(os.environ.get("MAX_PHOTOS", "200")),
    # Fun accessories overlaid on detected faces in the live stream. The master
    # switch gates the per-accessory toggles below.
    "accessories_enabled": os.environ.get("ACCESSORIES_ENABLED", "false").lower() == "true",
    "acc_glasses": os.environ.get("ACC_GLASSES", "false").lower() == "true",
    "acc_hat": os.environ.get("ACC_HAT", "false").lower() == "true",
    "acc_mustache": os.environ.get("ACC_MUSTACHE", "false").lower() == "true",
    "acc_beard": os.environ.get("ACC_BEARD", "false").lower() == "true",
    "acc_makeup": os.environ.get("ACC_MAKEUP", "false").lower() == "true",
}

# Keys that should never be sent back to the browser in clear text.
SECRET_KEYS = {"smtp_password"}


class Settings:
    """Thread-safe accessor for the persisted settings JSON file."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[str, Any] = dict(DEFAULT_SETTINGS)
        self._load()

    def _load(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
        CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
        FACES_DIR.mkdir(parents=True, exist_ok=True)
        if SETTINGS_FILE.exists():
            try:
                stored = json.loads(SETTINGS_FILE.read_text())
                # Merge so newly added default keys appear for old installs.
                merged = dict(DEFAULT_SETTINGS)
                merged.update({k: v for k, v in stored.items() if k in DEFAULT_SETTINGS})
                self._values = merged
            except (json.JSONDecodeError, OSError):
                self._values = dict(DEFAULT_SETTINGS)
        else:
            self._save_locked()

    def _save_locked(self) -> None:
        SETTINGS_FILE.write_text(json.dumps(self._values, indent=2))

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._values.get(key, default)

    def all(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._values)

    def public(self) -> dict[str, Any]:
        """Settings safe to render in the admin UI (secrets masked)."""
        with self._lock:
            out = dict(self._values)
        for key in SECRET_KEYS:
            out[key] = "********" if out.get(key) else ""
        return out

    def update(self, changes: dict[str, Any]) -> dict[str, Any]:
        """Apply validated changes and persist. Returns the new full settings."""
        with self._lock:
            for key, value in changes.items():
                if key not in DEFAULT_SETTINGS:
                    continue
                # Skip masked secrets so we don't overwrite real values.
                if key in SECRET_KEYS and value == "********":
                    continue
                self._values[key] = self._coerce(key, value)
            self._save_locked()
            return dict(self._values)

    @staticmethod
    def _coerce(key: str, value: Any) -> Any:
        default = DEFAULT_SETTINGS[key]
        if isinstance(default, bool):
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "yes", "on"}
            return bool(value)
        if isinstance(default, int):
            try:
                return int(value)
            except (TypeError, ValueError):
                return default
        if isinstance(default, float):
            try:
                return float(value)
            except (TypeError, ValueError):
                return default
        return "" if value is None else str(value)
