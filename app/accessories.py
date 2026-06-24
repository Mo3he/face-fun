"""Procedural face accessories drawn over detected faces.

Every overlay is derived from face landmarks (no external image assets), so the
feature adds no dependencies beyond the OpenCV/NumPy the camera worker already
uses. Colours are BGR to match OpenCV.
"""
from __future__ import annotations

import cv2
import numpy as np

# Per-accessory setting keys, also defining the render order (drawn back to
# front so e.g. glasses sit on top of makeup and the hat sits on top of all).
ACCESSORIES = ("makeup", "beard", "mustache", "glasses", "hat")


def _pts(landmarks: dict, key: str) -> np.ndarray:
    return np.array(landmarks.get(key, []), dtype=np.float64)


def _center(landmarks: dict, key: str) -> np.ndarray | None:
    pts = _pts(landmarks, key)
    return pts.mean(axis=0) if len(pts) else None


def draw_accessories(frame: np.ndarray, detections, options: dict) -> np.ndarray:
    """Draw the enabled accessories on every detection that has landmarks.

    ``options`` maps accessory names from :data:`ACCESSORIES` to booleans. The
    frame is modified in place and also returned for convenience.
    """
    if not options:
        return frame
    for d in detections:
        landmarks = getattr(d, "landmarks", None)
        if not landmarks:
            continue
        if options.get("makeup"):
            _makeup(frame, landmarks)
        if options.get("beard"):
            _beard(frame, landmarks)
        if options.get("mustache"):
            _mustache(frame, landmarks)
        if options.get("glasses"):
            _glasses(frame, landmarks)
        if options.get("hat"):
            _hat(frame, landmarks)
    return frame


def _glasses(frame: np.ndarray, lm: dict) -> None:
    left = _center(lm, "left_eye")
    right = _center(lm, "right_eye")
    if left is None or right is None:
        return
    span = float(np.linalg.norm(right - left))
    radius = int(max(8, span * 0.35))
    color = (25, 25, 25)
    lc = tuple(left.astype(int))
    rc = tuple(right.astype(int))
    cv2.circle(frame, lc, radius, color, 3)
    cv2.circle(frame, rc, radius, color, 3)
    cv2.line(frame, lc, rc, color, 3)
    # Temple arms extend outward from each lens, away from the bridge.
    direction = right - left
    unit = direction / (np.linalg.norm(direction) + 1e-6)
    left_start = (left - unit * radius).astype(int)
    left_end = (left - unit * radius * 3.0).astype(int)
    right_start = (right + unit * radius).astype(int)
    right_end = (right + unit * radius * 3.0).astype(int)
    cv2.line(frame, tuple(left_start), tuple(left_end), color, 3)
    cv2.line(frame, tuple(right_start), tuple(right_end), color, 3)


def _hat(frame: np.ndarray, lm: dict) -> None:
    chin = _pts(lm, "chin")
    brows = np.vstack([_pts(lm, "left_eyebrow"), _pts(lm, "right_eyebrow")])
    if len(chin) == 0 or len(brows) == 0:
        return
    left, right = chin[0], chin[-1]
    face_width = float(np.linalg.norm(right - left))
    brow_top = float(brows[:, 1].min())
    chin_bottom = float(chin[:, 1].max())
    face_height = chin_bottom - brow_top
    cx = (left[0] + right[0]) / 2.0
    brim_y = brow_top - face_height * 0.12
    crown_h = face_height * 0.6
    half = face_width * 0.55
    brim = (40, 40, 40)
    crown = (45, 45, 45)
    band = (40, 40, 170)
    # Brim, crown and a coloured band, drawn bottom-up.
    cv2.ellipse(
        frame, (int(cx), int(brim_y)),
        (int(half * 1.15), max(4, int(face_height * 0.09))),
        0, 0, 360, brim, cv2.FILLED,
    )
    cv2.rectangle(
        frame,
        (int(cx - half * 0.72), int(brim_y - crown_h)),
        (int(cx + half * 0.72), int(brim_y)),
        crown, cv2.FILLED,
    )
    cv2.rectangle(
        frame,
        (int(cx - half * 0.72), int(brim_y - crown_h * 0.22)),
        (int(cx + half * 0.72), int(brim_y)),
        band, cv2.FILLED,
    )


def _mustache(frame: np.ndarray, lm: dict) -> None:
    nose = _pts(lm, "nose_tip")
    top_lip = _pts(lm, "top_lip")
    if len(nose) == 0 or len(top_lip) == 0:
        return
    left = top_lip[0]
    right = top_lip[6] if len(top_lip) > 6 else top_lip[-1]
    width = float(np.linalg.norm(right - left))
    cx = (left[0] + right[0]) / 2.0
    cy = (float(nose[:, 1].mean()) + float(top_lip[:, 1].min())) / 2.0
    axes = (max(6, int(width * 0.6)), max(3, int(width * 0.22)))
    cv2.ellipse(frame, (int(cx), int(cy)), axes, 0, 0, 360, (30, 30, 30), cv2.FILLED)


def _beard(frame: np.ndarray, lm: dict) -> None:
    chin = _pts(lm, "chin")
    if len(chin) == 0:
        return
    jaw = chin.astype(np.int32)
    bottom_lip = _pts(lm, "bottom_lip")
    if len(bottom_lip):
        lip = bottom_lip.astype(np.int32)
        lip = lip[np.argsort(lip[:, 0])]
        poly = np.vstack([jaw, lip[::-1]])
    else:
        poly = jaw
    overlay = frame.copy()
    cv2.fillPoly(overlay, [poly], (35, 45, 70))
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)


def _makeup(frame: np.ndarray, lm: dict) -> None:
    overlay = frame.copy()
    top_lip = _pts(lm, "top_lip")
    bottom_lip = _pts(lm, "bottom_lip")
    if len(top_lip) and len(bottom_lip):
        lips = np.vstack([top_lip, bottom_lip]).astype(np.int32)
        cv2.fillPoly(overlay, [cv2.convexHull(lips)], (90, 90, 220))
    chin = _pts(lm, "chin")
    nose = _center(lm, "nose_tip")
    if len(chin) and nose is not None:
        radius = int(float(np.linalg.norm(chin[-1] - chin[0])) * 0.08) + 5
        for idx in (3, 13):
            if idx < len(chin):
                cheek = chin[idx] * 0.6 + nose * 0.4
                cv2.circle(overlay, tuple(cheek.astype(int)), radius, (120, 120, 235), cv2.FILLED)
    cv2.addWeighted(overlay, 0.4, frame, 0.6, 0, frame)
