"""In-memory cache of known face encodings, backed by the database.

Keeping the encodings in memory avoids hitting SQLite on every processed frame.
The cache is refreshed whenever a face is enrolled or deleted.
"""
from __future__ import annotations

import threading

import face_recognition
import numpy as np

from .database import Database

# face_recognition (dlib) keeps process-wide, non-thread-safe model singletons
# (the shape predictor and the ResNet encoder). Calling them from the camera
# worker thread and a web request thread at the same time segfaults the process.
# Every call into dlib-backed detection/encoding must hold this lock.
recognition_lock = threading.Lock()


class FaceStore:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._lock = threading.Lock()
        self._ids: list[int] = []
        self._names: list[str] = []
        self._encodings: list[np.ndarray] = []
        self.reload()

    def reload(self) -> None:
        ids, names, encs = self._db.all_encodings()
        with self._lock:
            self._ids, self._names, self._encodings = ids, names, encs

    def enroll(self, name: str, encoding: np.ndarray) -> int:
        face_id = self._db.add_face(name, encoding)
        self.reload()
        return face_id

    def delete(self, face_id: int) -> None:
        self._db.delete_face(face_id)
        self.reload()

    def identify(self, encoding: np.ndarray, tolerance: float) -> str:
        """Return the best-matching name, or 'Unknown' when nothing matches."""
        with self._lock:
            if not self._encodings:
                return "Unknown"
            known = self._encodings
            names = self._names
        distances = face_recognition.face_distance(known, encoding)
        best = int(np.argmin(distances))
        if distances[best] <= tolerance:
            return names[best]
        return "Unknown"
