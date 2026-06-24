"""SQLite persistence for enrolled faces and captured photos."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import numpy as np


class Database:
    def __init__(self, path: Path) -> None:
        self._path = str(path)
        self._lock = threading.Lock()
        # check_same_thread=False because the camera worker thread and the web
        # request threads share this connection; all access is serialised by
        # the lock below.
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS faces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    encoding BLOB NOT NULL,
                    image TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS photos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    labels TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS captures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    label TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                """
            )
            # Migration for installs created before the faces.image column existed.
            cols = {
                r["name"]
                for r in self._conn.execute("PRAGMA table_info(faces)").fetchall()
            }
            if "image" not in cols:
                self._conn.execute("ALTER TABLE faces ADD COLUMN image TEXT")
            self._conn.commit()

    # ---- faces ---------------------------------------------------------
    def add_face(self, name: str, encoding: np.ndarray, image: str | None = None) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO faces (name, encoding, image) VALUES (?, ?, ?)",
                (name, encoding.astype(np.float64).tobytes(), image),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def list_faces(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, name, image, created_at FROM faces ORDER BY name"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_face(self, face_id: int) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, name, image, created_at FROM faces WHERE id = ?",
                (face_id,),
            ).fetchone()
        return dict(row) if row else None

    def all_encodings(self) -> tuple[list[int], list[str], list[np.ndarray]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, name, encoding FROM faces"
            ).fetchall()
        ids, names, encs = [], [], []
        for r in rows:
            ids.append(int(r["id"]))
            names.append(r["name"])
            encs.append(np.frombuffer(r["encoding"], dtype=np.float64))
        return ids, names, encs

    def delete_face(self, face_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM faces WHERE id = ?", (face_id,))
            self._conn.commit()

    # ---- photos --------------------------------------------------------
    def add_photo(self, filename: str, labels: str) -> dict:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO photos (filename, labels) VALUES (?, ?)",
                (filename, labels),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT id, filename, labels, created_at FROM photos WHERE id = ?",
                (cur.lastrowid,),
            ).fetchone()
        return dict(row)

    def list_photos(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, filename, labels, created_at FROM photos ORDER BY id DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_photos(self, ids: list[int]) -> list[dict]:
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT id, filename, labels, created_at FROM photos WHERE id IN ({placeholders})",
                ids,
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_photo(self, photo_id: int) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT filename FROM photos WHERE id = ?", (photo_id,)
            ).fetchone()
            if row is None:
                return None
            self._conn.execute("DELETE FROM photos WHERE id = ?", (photo_id,))
            self._conn.commit()
        return row["filename"]

    # ---- captures (auto-saved cropped faces) ---------------------------
    def add_capture(self, filename: str, label: str) -> dict:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO captures (filename, label) VALUES (?, ?)",
                (filename, label),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT id, filename, label, created_at FROM captures WHERE id = ?",
                (cur.lastrowid,),
            ).fetchone()
        return dict(row)

    def list_captures(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, filename, label, created_at FROM captures ORDER BY id DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_captures(self, ids: list[int]) -> list[dict]:
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT id, filename, label, created_at FROM captures WHERE id IN ({placeholders})",
                ids,
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_capture(self, capture_id: int) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT filename FROM captures WHERE id = ?", (capture_id,)
            ).fetchone()
            if row is None:
                return None
            self._conn.execute("DELETE FROM captures WHERE id = ?", (capture_id,))
            self._conn.commit()
        return row["filename"]
