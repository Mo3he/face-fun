"""Face Fun - FastAPI application wiring the camera, recognition and web UI."""
from __future__ import annotations

import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import config
from .auth import require_admin
from .camera import Camera
from .config import Settings
from .database import Database
from .email_utils import EmailError, send_photos, send_test
from .faces import FaceStore

BASE_DIR = Path(__file__).resolve().parent

settings = Settings()
database = Database(config.DB_FILE)
face_store = FaceStore(database)
camera = Camera(settings, face_store)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SAFE_NAME = re.compile(r"[^A-Za-z0-9 _\-]")


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
def admin_page(request: Request, _: str = Depends(require_admin)):
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
        "enrolled": database.list_faces(),
    }


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
    return record


@app.get("/photos")
def list_photos():
    return database.list_photos()


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
# Admin API (locked behind HTTP Basic auth)
# --------------------------------------------------------------------------
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
    face_store.delete(face_id)
    return {"ok": True}
