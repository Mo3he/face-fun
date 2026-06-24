"""RTSP capture worker that produces an annotated MJPEG stream.

A single background thread owns the OpenCV ``VideoCapture``. It continuously
reads frames, runs face recognition every ``detect_every`` frames (on a
downscaled copy for speed) and re-draws the most recent detections on every
frame so the live stream stays smooth. The latest annotated JPEG and the latest
raw frame are exposed under a lock for the web layer to consume.
"""
from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

import cv2
import face_recognition
import numpy as np

from . import config
from .capture import dedup_new_faces
from .config import Settings
from .database import Database
from .faces import FaceStore, recognition_lock

# Scale frames down before running detection. 0.25 => quarter size, which is a
# good speed/accuracy trade-off for typical RTSP resolutions.
DETECT_SCALE = 0.25

# Minimum seconds before the same face can be auto-saved again, so a face that
# lingers in view does not flood the captures gallery.
CAPTURE_COOLDOWN = 30.0

# Max face-encoding distance for two detections to count as the same person when
# deduplicating captures (mirrors the recognition default).
CAPTURE_DEDUP_TOLERANCE = 0.6


class Detection:
    __slots__ = ("top", "right", "bottom", "left", "name")

    def __init__(self, top: int, right: int, bottom: int, left: int, name: str):
        self.top, self.right, self.bottom, self.left, self.name = top, right, bottom, left, name


class Camera:
    def __init__(self, settings: Settings, face_store: FaceStore, database: Database) -> None:
        self._settings = settings
        self._faces = face_store
        self._database = database
        self._lock = threading.Lock()
        self._jpeg: bytes | None = None
        self._raw: np.ndarray | None = None
        self._detections: list[Detection] = []
        self._running = False
        self._thread: threading.Thread | None = None
        self._generation = 0  # bumped on restart so the loop reconnects
        # Auto-capture bookkeeping: recently saved face encodings with the last
        # time each was seen, used to avoid re-saving the same person.
        self._recent_captures: list[tuple[np.ndarray, float]] = []
        self.connected = False
        self.last_error = ""

    # ---- lifecycle -----------------------------------------------------
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, name="camera", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        thread = self._thread
        if thread is not None:
            thread.join(timeout=3)
        self._thread = None

    def restart(self) -> None:
        """Force the worker to drop the current stream and reconnect."""
        self._generation += 1

    # ---- worker --------------------------------------------------------
    def _run(self) -> None:
        while self._running:
            url = self._settings.get("rtsp_url")
            if not url:
                self.connected = False
                self.last_error = "No RTSP URL configured."
                self._set_placeholder("Set the RTSP URL in the admin settings")
                time.sleep(1.0)
                continue

            cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
            # Keep latency low by not buffering many frames.
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if not cap.isOpened():
                self.connected = False
                self.last_error = "Could not open RTSP stream."
                self._set_placeholder("Cannot connect to the camera")
                cap.release()
                time.sleep(2.0)
                continue

            self.connected = True
            self.last_error = ""
            generation = self._generation
            self._stream_loop(cap, generation)
            cap.release()

    def _stream_loop(self, cap: "cv2.VideoCapture", generation: int) -> None:
        frame_index = 0
        failures = 0
        while self._running and generation == self._generation:
            ok, frame = cap.read()
            if not ok or frame is None:
                failures += 1
                if failures > 30:
                    self.connected = False
                    self.last_error = "Lost connection to the camera."
                    break
                time.sleep(0.05)
                continue
            failures = 0

            detect_every = max(1, int(self._settings.get("detect_every", 5)))
            if frame_index % detect_every == 0:
                self._detections, encodings = self._detect(frame)
                self._maybe_capture(frame, self._detections, encodings)
            frame_index += 1

            annotated = self._annotate(frame, self._detections)
            ok, buffer = cv2.imencode(".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            if ok:
                with self._lock:
                    self._jpeg = buffer.tobytes()
                    self._raw = frame

    def _detect(self, frame: np.ndarray) -> tuple[list[Detection], list[np.ndarray]]:
        tolerance = float(self._settings.get("recognition_tolerance", 0.6))
        small = cv2.resize(frame, (0, 0), fx=DETECT_SCALE, fy=DETECT_SCALE)
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        with recognition_lock:
            locations = face_recognition.face_locations(rgb)
            encodings = face_recognition.face_encodings(rgb, locations)
        results: list[Detection] = []
        inv = 1.0 / DETECT_SCALE
        for (top, right, bottom, left), encoding in zip(locations, encodings):
            name = self._faces.identify(encoding, tolerance)
            results.append(
                Detection(
                    int(top * inv),
                    int(right * inv),
                    int(bottom * inv),
                    int(left * inv),
                    name,
                )
            )
        return results, list(encodings)

    @staticmethod
    def _annotate(frame: np.ndarray, detections: list[Detection]) -> np.ndarray:
        out = frame.copy()
        for d in detections:
            known = d.name != "Unknown"
            color = (0, 200, 0) if known else (0, 0, 255)
            cv2.rectangle(out, (d.left, d.top), (d.right, d.bottom), color, 2)
            label = d.name
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
            cv2.rectangle(out, (d.left, d.bottom), (d.left + tw + 10, d.bottom + th + 12), color, cv2.FILLED)
            cv2.putText(
                out,
                label,
                (d.left + 5, d.bottom + th + 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2,
            )
        return out

    def _set_placeholder(self, message: str) -> None:
        img = np.zeros((360, 640, 3), dtype=np.uint8)
        cv2.putText(img, message, (20, 180), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        ok, buffer = cv2.imencode(".jpg", img)
        if ok:
            with self._lock:
                self._jpeg = buffer.tobytes()

    # ---- auto capture --------------------------------------------------
    @staticmethod
    def _crop_face(frame: np.ndarray, d: "Detection") -> np.ndarray | None:
        """Return a margin-padded crop of the detected face, or None."""
        h, w = frame.shape[:2]
        margin_y = int((d.bottom - d.top) * 0.25)
        margin_x = int((d.right - d.left) * 0.25)
        top = max(0, d.top - margin_y)
        bottom = min(h, d.bottom + margin_y)
        left = max(0, d.left - margin_x)
        right = min(w, d.right + margin_x)
        if bottom <= top or right <= left:
            return None
        crop = frame[top:bottom, left:right]
        return crop if crop.size else None

    def _maybe_capture(
        self,
        frame: np.ndarray,
        detections: list["Detection"],
        encodings: list[np.ndarray],
    ) -> None:
        """Save a cropped image when a genuinely new face appears in view."""
        if not detections:
            return
        now = time.time()
        new_indices = dedup_new_faces(
            self._recent_captures, encodings, now, CAPTURE_COOLDOWN, CAPTURE_DEDUP_TOLERANCE
        )
        if not new_indices:
            return
        saved = False
        for i in new_indices:
            d = detections[i]
            crop = self._crop_face(frame, d)
            if crop is None:
                continue
            ok, buffer = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
            if not ok:
                continue
            filename = f"{int(now)}_{uuid.uuid4().hex[:8]}.jpg"
            try:
                (config.CAPTURES_DIR / filename).write_bytes(buffer.tobytes())
                self._database.add_capture(filename, d.name)
                saved = True
            except OSError:
                continue
        if saved:
            self._prune_captures()

    def _prune_captures(self) -> None:
        """Delete the oldest captures past the configured retention limit."""
        keep = int(self._settings.get("max_captures", 0))
        if keep <= 0:
            return
        for filename in self._database.prune_captures(keep):
            target = config.CAPTURES_DIR / Path(filename).name
            try:
                if target.exists():
                    target.unlink()
            except OSError:
                continue

    # ---- consumers -----------------------------------------------------
    def get_jpeg(self) -> bytes | None:
        with self._lock:
            return self._jpeg

    def get_raw_frame(self) -> np.ndarray | None:
        with self._lock:
            return None if self._raw is None else self._raw.copy()

    def current_labels(self) -> list[str]:
        return [d.name for d in self._detections]

    def enroll_current_face(self, name: str) -> tuple[bool, str]:
        """Enroll the largest face in the latest raw frame under ``name``."""
        frame = self.get_raw_frame()
        if frame is None:
            return False, "No video frame available yet."
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        with recognition_lock:
            locations = face_recognition.face_locations(rgb)
            if not locations:
                return False, "No face detected. Make sure your face is clearly visible."
            # Choose the largest detected face.
            largest = max(locations, key=lambda loc: (loc[2] - loc[0]) * (loc[1] - loc[3]))
            encodings = face_recognition.face_encodings(rgb, [largest])
        if not encodings:
            return False, "Could not compute a face encoding. Try again."
        image = self._save_enroll_thumb(frame, largest)
        self._faces.enroll(name, encodings[0], image)
        return True, f"Enrolled {name}."

    @staticmethod
    def _save_enroll_thumb(frame: np.ndarray, location: tuple[int, int, int, int]) -> str | None:
        """Save a cropped thumbnail of an enrolled face. Returns the filename."""
        top, right, bottom, left = location
        d = Detection(top, right, bottom, left, "")
        crop = Camera._crop_face(frame, d)
        if crop is None:
            return None
        ok, buffer = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        if not ok:
            return None
        filename = f"{int(time.time())}_{uuid.uuid4().hex[:8]}.jpg"
        try:
            (config.FACES_DIR / filename).write_bytes(buffer.tobytes())
        except OSError:
            return None
        return filename

    def capture_annotated_jpeg(self) -> bytes | None:
        """Return a freshly annotated JPEG of the current frame for a photo."""
        frame = self.get_raw_frame()
        if frame is None:
            return self.get_jpeg()
        annotated = self._annotate(frame, self._detections)
        ok, buffer = cv2.imencode(".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        return buffer.tobytes() if ok else None
