"""Tests for the SQLite layer (needs numpy)."""
import numpy as np
import pytest

pytest.importorskip("numpy")

from app.database import Database  # noqa: E402


def _enc(value: float) -> np.ndarray:
    arr = np.zeros(128, dtype=np.float64)
    arr[0] = value
    return arr


def test_face_crud(tmp_path):
    db = Database(tmp_path / "t.db")
    fid = db.add_face("Alice", _enc(1.0), "alice.jpg")
    faces = db.list_faces()
    assert len(faces) == 1
    assert faces[0]["name"] == "Alice"
    assert faces[0]["image"] == "alice.jpg"

    rec = db.get_face(fid)
    assert rec is not None
    assert rec["image"] == "alice.jpg"

    ids, names, encs = db.all_encodings()
    assert names == ["Alice"]
    assert np.allclose(encs[0], _enc(1.0))

    db.delete_face(fid)
    assert db.list_faces() == []


def test_capture_pagination_and_prune(tmp_path):
    db = Database(tmp_path / "t.db")
    for i in range(5):
        db.add_capture(f"f{i}.jpg", "Unknown")
    assert len(db.list_captures()) == 5

    page = db.list_captures(limit=2, offset=0)
    assert len(page) == 2

    removed = db.prune_captures(3)
    assert len(removed) == 2
    assert len(db.list_captures()) == 3

    ids = [c["id"] for c in db.list_captures()]
    assert len(db.get_captures(ids)) == 3


def test_prune_keep_zero_is_noop(tmp_path):
    db = Database(tmp_path / "t.db")
    db.add_capture("only.jpg", "Unknown")
    assert db.prune_captures(0) == []
    assert len(db.list_captures()) == 1


def test_photo_prune(tmp_path):
    db = Database(tmp_path / "t.db")
    for i in range(4):
        db.add_photo(f"p{i}.jpg", "")
    removed = db.prune_photos(2)
    assert len(removed) == 2
    assert len(db.list_photos()) == 2
