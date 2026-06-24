"""Face Fun - FastAPI application wiring the camera, recognition and web UI."""
from __future__ import annotations

import io
import re
import time
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import config
from .accessories import ACCESSORIES
from .auth import (
    check_rate_limit,
    create_session,
    destroy_session,
    record_failure,
    require_admin,
    reset_failures,
    verify_credentials,
)
from .camera import Camera
from .config import Settings
from .database import Database
from .email_utils import EmailError, send_photos, send_test
from .faces import FaceStore

BASE_DIR = Path(__file__).resolve().parent

settings = Settings()
database = Database(config.DB_FILE)
face_store = FaceStore(database)
camera = Camera(settings, face_store, database)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SAFE_NAME = re.compile(r"[^A-Za-z0-9 _\-]")

# Accessory toggles users may change from the public page (cosmetic only).
ACCESSORY_KEYS = {"accessories_enabled", *(f"acc_{name}" for name in ACCESSORIES)}


@asynccontextmanager
async def lifespan(_: FastAPI):
    camera.start()
    yield
    camera.stop()


app = FastAPI(title="Face Fun", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    # The page itself is a shell; it gates every action behind a fresh login
    # and only loads admin data after the user authenticates.
    return templates.TemplateResponse("admin.html", {"request": request})


# --------------------------------------------------------------------------
# Video stream
# --------------------------------------------------------------------------
def _mjpeg_generator():
    boundary = b"--frame"
    while True:
        frame = camera.get_jpeg()
        if frame is None:
            time.sleep(0.05)
            continue
        yield (
            boundary
            + b"\r\nContent-Type: image/jpeg\r\nContent-Length: "
            + str(len(frame)).encode()
            + b"\r\n\r\n"
            + frame
            + b"\r\n"
        )
        # ~20 fps cap for the browser stream.
        time.sleep(0.05)


@app.get("/video_feed")
def video_feed():
    return StreamingResponse(
        _mjpeg_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/status")
def status():
    return {
        "connected": camera.connected,
        "error": camera.last_error,
        "labels": camera.current_labels(),
    }


@app.get("/healthz")
def healthz():
    return {"status": "ok", "camera_connected": camera.connected}


# --------------------------------------------------------------------------
# Accessories (public: any viewer can change what the stream overlays)
# --------------------------------------------------------------------------
def _accessory_state() -> dict:
    s = settings.all()
    return {key: bool(s.get(key, False)) for key in ACCESSORY_KEYS}


@app.get("/accessories")
def get_accessories():
    return _accessory_state()


@app.post("/accessories")
async def update_accessories(request: Request):
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid request body.")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid request body.")
    # Only the cosmetic accessory keys are accepted here; everything else is
    # ignored so this public endpoint can't touch camera or SMTP settings.
    changes = {k: bool(v) for k, v in payload.items() if k in ACCESSORY_KEYS}
    settings.update(changes)
    return _accessory_state()


# --------------------------------------------------------------------------
# Enrollment
# --------------------------------------------------------------------------
@app.post("/enroll")
def enroll(name: str = Form(...)):
    clean = _SAFE_NAME.sub("", name).strip()
    if not clean:
        raise HTTPException(status_code=400, detail="Please enter a valid name.")
    ok, message = camera.enroll_current_face(clean)
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return {"ok": True, "message": message}


# --------------------------------------------------------------------------
# Photos
# --------------------------------------------------------------------------
@app.post("/photo")
def take_photo():
    jpeg = camera.capture_annotated_jpeg()
    if jpeg is None:
        raise HTTPException(status_code=503, detail="No video frame available yet.")
    filename = f"{int(time.time())}_{uuid.uuid4().hex[:8]}.jpg"
    (config.PHOTOS_DIR / filename).write_bytes(jpeg)
    labels = ", ".join(sorted(set(camera.current_labels())))
    record = database.add_photo(filename, labels)
    _prune_photos()
    return record


def _prune_photos() -> None:
    keep = int(settings.get("max_photos", 0))
    if keep <= 0:
        return
    for filename in database.prune_photos(keep):
        target = config.PHOTOS_DIR / Path(filename).name
        if target.exists():
            target.unlink()


@app.get("/photos")
def list_photos(limit: int | None = None, offset: int = 0):
    return database.list_photos(limit=limit, offset=max(0, offset))


@app.get("/photos/{filename}")
def get_photo(filename: str):
    safe = Path(filename).name  # strip any path traversal
    path = config.PHOTOS_DIR / safe
    if not path.exists():
        raise HTTPException(status_code=404, detail="Photo not found.")
    return FileResponse(path, media_type="image/jpeg")


@app.delete("/photos/{photo_id}")
def delete_photo(photo_id: int):
    filename = database.delete_photo(photo_id)
    if filename is None:
        raise HTTPException(status_code=404, detail="Photo not found.")
    target = config.PHOTOS_DIR / Path(filename).name
    if target.exists():
        target.unlink()
    return {"ok": True}


# --------------------------------------------------------------------------
# Email
# --------------------------------------------------------------------------
@app.post("/email")
def email_photos(recipient: str = Form(...), photo_ids: str = Form(...)):
    recipient = recipient.strip()
    if not _EMAIL_RE.match(recipient):
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")
    try:
        ids = [int(x) for x in photo_ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid photo selection.")
    if not ids:
        raise HTTPException(status_code=400, detail="Select at least one photo.")

    records = database.get_photos(ids)
    if not records:
        raise HTTPException(status_code=404, detail="Selected photos were not found.")
    paths = [config.PHOTOS_DIR / Path(r["filename"]).name for r in records]

    try:
        send_photos(settings, recipient, paths)
    except EmailError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"ok": True, "message": f"Sent {len(paths)} photo(s) to {recipient}."}


# --------------------------------------------------------------------------
# Admin API (locked behind a session token)
# --------------------------------------------------------------------------
@app.post("/admin/login")
def admin_login(request: Request, username: str = Form(...), password: str = Form(...)):
    ip = request.client.host if request.client else "unknown"
    check_rate_limit(ip)
    if not verify_credentials(username, password):
        record_failure(ip)
        raise HTTPException(status_code=401, detail="Invalid administrator credentials.")
    reset_failures(ip)
    return {"ok": True, "token": create_session()}


@app.post("/admin/logout")
def admin_logout(token: str = Depends(require_admin)):
    destroy_session(token)
    return {"ok": True}


@app.get("/admin/settings")
def get_settings(_: str = Depends(require_admin)):
    return settings.public()


@app.post("/admin/settings")
async def update_settings(request: Request, _: str = Depends(require_admin)):
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid settings payload.")
    previous_rtsp = settings.get("rtsp_url")
    updated = settings.update(payload)
    if updated.get("rtsp_url") != previous_rtsp:
        camera.restart()
    return JSONResponse({"ok": True, "settings": settings.public()})


@app.post("/admin/test-email")
def admin_test_email(recipient: str = Form(...), _: str = Depends(require_admin)):
    recipient = recipient.strip()
    if not _EMAIL_RE.match(recipient):
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")
    try:
        send_test(settings, recipient)
    except EmailError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"ok": True, "message": f"Test email sent to {recipient}."}


@app.delete("/admin/faces/{face_id}")
def admin_delete_face(face_id: int, _: str = Depends(require_admin)):
    record = database.get_face(face_id)
    face_store.delete(face_id)
    if record and record.get("image"):
        target = config.FACES_DIR / Path(record["image"]).name
        if target.exists():
            target.unlink()
    return {"ok": True}


@app.get("/admin/faces")
def admin_list_faces(_: str = Depends(require_admin)):
    return database.list_faces()


@app.get("/faces/image/{filename}")
def get_face_image(filename: str, _: str = Depends(require_admin)):
    safe = Path(filename).name  # strip any path traversal
    path = config.FACES_DIR / safe
    if not path.exists():
        raise HTTPException(status_code=404, detail="Image not found.")
    return FileResponse(path, media_type="image/jpeg")


# --------------------------------------------------------------------------
# Captures (auto-saved cropped faces, managed from the admin tab)
# --------------------------------------------------------------------------
@app.get("/admin/captures")
def admin_list_captures(limit: int | None = None, offset: int = 0, _: str = Depends(require_admin)):
    return database.list_captures(limit=limit, offset=max(0, offset))


@app.delete("/admin/captures/{capture_id}")
def admin_delete_capture(capture_id: int, _: str = Depends(require_admin)):
    filename = database.delete_capture(capture_id)
    if filename is None:
        raise HTTPException(status_code=404, detail="Capture not found.")
    target = config.CAPTURES_DIR / Path(filename).name
    if target.exists():
        target.unlink()
    return {"ok": True}


@app.post("/admin/captures/download")
async def admin_download_captures(request: Request, _: str = Depends(require_admin)):
    payload = await request.json()
    raw_ids = payload.get("ids") if isinstance(payload, dict) else None
    try:
        ids = [int(x) for x in (raw_ids or [])]
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid selection.")
    if not ids:
        raise HTTPException(status_code=400, detail="Select at least one capture.")
    records = database.get_captures(ids)
    if not records:
        raise HTTPException(status_code=404, detail="No captures found.")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for record in records:
            path = config.CAPTURES_DIR / Path(record["filename"]).name
            if path.exists():
                archive.write(path, arcname=record["filename"])
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=captures.zip"},
    )


@app.get("/captures/{filename}")
def get_capture(filename: str, _: str = Depends(require_admin)):
    safe = Path(filename).name  # strip any path traversal
    path = config.CAPTURES_DIR / safe
    if not path.exists():
        raise HTTPException(status_code=404, detail="Capture not found.")
    return FileResponse(path, media_type="image/jpeg")
