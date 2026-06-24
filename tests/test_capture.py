"""Tests for the pure capture de-duplication helper (numpy only)."""
import numpy as np
import pytest

pytest.importorskip("numpy")

from app.capture import dedup_new_faces  # noqa: E402


def _enc(value: float) -> np.ndarray:
    arr = np.zeros(128, dtype=np.float64)
    arr[0] = value
    return arr


def test_first_sighting_is_new():
    recent: list = []
    idx = dedup_new_faces(recent, [_enc(0.0)], now=100.0, cooldown=30.0, tolerance=0.6)
    assert idx == [0]
    assert len(recent) == 1


def test_same_face_within_cooldown_not_recaptured():
    recent: list = []
    dedup_new_faces(recent, [_enc(0.0)], now=100.0, cooldown=30.0, tolerance=0.6)
    idx = dedup_new_faces(recent, [_enc(0.0)], now=110.0, cooldown=30.0, tolerance=0.6)
    assert idx == []


def test_distinct_faces_are_each_new():
    recent: list = []
    idx = dedup_new_faces(
        recent, [_enc(0.0), _enc(10.0)], now=100.0, cooldown=30.0, tolerance=0.6
    )
    assert idx == [0, 1]


def test_recapture_after_cooldown_elapses():
    recent: list = []
    dedup_new_faces(recent, [_enc(0.0)], now=100.0, cooldown=30.0, tolerance=0.6)
    idx = dedup_new_faces(recent, [_enc(0.0)], now=200.0, cooldown=30.0, tolerance=0.6)
    assert idx == [0]
