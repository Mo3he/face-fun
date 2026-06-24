# AGENTS.md

Face Fun is a Dockerized FastAPI web app that pulls an RTSP camera stream,
recognizes/labels enrolled faces in real time, captures photos, and emails them
via SMTP. Operator settings live behind an admin-only tab. See [README.md](README.md)
for setup, usage, and deployment details (don't duplicate them here).

## Architecture

Single FastAPI process. A background thread owns the camera; web requests read
shared state from it under locks.

- [app/main.py](app/main.py) - FastAPI routes (public + admin), MJPEG stream, app wiring.
- [app/camera.py](app/camera.py) - RTSP capture + recognition worker thread; produces annotated MJPEG.
- [app/faces.py](app/faces.py) - in-memory encoding cache backed by SQLite; matching logic.
- [app/database.py](app/database.py) - SQLite (enrolled faces + photo metadata).
- [app/config.py](app/config.py) - env config + admin-editable settings persisted to `DATA_DIR/settings.json`.
- [app/email_utils.py](app/email_utils.py) - SMTP sending.
- [app/auth.py](app/auth.py) - HTTP Basic auth for `/admin*`.
- [app/templates/](app/templates), [app/static/](app/static) - Jinja pages + vanilla JS/CSS (no build step).

## Validate changes

There is no test suite. After editing Python, run:

```bash
python3 -m py_compile app/*.py   # syntax check
ruff check app                   # lint (CI enforces this; must pass clean)
```

## Critical, non-obvious rules

- **dlib is not thread-safe.** Every call into `face_recognition` (detection or
  encoding) MUST hold `recognition_lock` from [app/faces.py](app/faces.py). The camera
  worker and request threads call dlib concurrently; unguarded calls segfault the
  process. This already caused a crash-on-enroll bug.
- **Do not put secrets in the image or in code.** Admin credentials come from
  `ADMIN_USERNAME`/`ADMIN_PASSWORD` env vars only. RTSP/SMTP settings persist to
  `DATA_DIR/settings.json` on the data volume. Secret keys are masked in
  `Settings.public()`, keep new secrets out of API responses.
- **Settings flow:** new operational settings must be added to `DEFAULT_SETTINGS`
  in [app/config.py](app/config.py) (with an env default) so they persist and round-trip
  through the admin UI; add the key to `SECRET_KEYS` if sensitive.
- **`/data` is the only writable state** (SQLite, photos, settings.json), mounted
  as a Docker/Podman volume. Don't write app state elsewhere.

## Environment gotchas

- `podman-compose up -d` reuses the existing container after a rebuild. Use
  `podman-compose up -d --force-recreate` (or `down` then `up`) to run new code.
- The GitHub owner is `Mo3he` but GHCR refs must be lowercase: the image is
  `ghcr.io/mo3he/face-fun`. Keep image references lowercase.

## CI / image publishing

- [.github/workflows/ci.yml](.github/workflows/ci.yml) - compile + ruff on push/PR.
- [.github/workflows/publish.yml](.github/workflows/publish.yml) - builds the multi-arch image on
  native per-arch runners (no QEMU), pushes by digest, then merges a manifest and
  tags it. First build compiles dlib (~5 min); cached builds are fast.
