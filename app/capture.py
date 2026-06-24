"""Pure helper for deciding which detected faces are new enough to save.

Kept free of OpenCV/dlib imports so it can be unit-tested without the heavy
recognition stack.
"""
from __future__ import annotations

import numpy as np


def dedup_new_faces(
    recent: list[tuple[np.ndarray, float]],
    encodings: list[np.ndarray],
    now: float,
    cooldown: float,
    tolerance: float,
) -> list[int]:
    """Return indices of ``encodings`` that represent newly seen faces.

    ``recent`` is a list of ``(encoding, last_seen_timestamp)`` and is mutated in
    place: stale entries (older than ``cooldown``) are dropped, entries matching a
    current face have their timestamp refreshed, and genuinely new faces are
    appended. A face counts as "new" when it is farther than ``tolerance`` from
    every remembered encoding, so the same person lingering in view is only saved
    once until they leave for longer than ``cooldown``.
    """
    recent[:] = [(enc, ts) for (enc, ts) in recent if now - ts < cooldown]
    new_indices: list[int] = []
    for i, encoding in enumerate(encodings):
        matched = False
        for j, (remembered, _ts) in enumerate(recent):
            if float(np.linalg.norm(remembered - encoding)) <= tolerance:
                recent[j] = (remembered, now)
                matched = True
                break
        if matched:
            continue
        recent.append((encoding, now))
        new_indices.append(i)
    return new_indices
