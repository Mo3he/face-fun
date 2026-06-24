# Face Fun

A web app that pulls an RTSP video stream from a camera (designed with Axis
cameras in mind, but any RTSP source works), shows the live video, recognizes
faces in real time and labels them with a name. Put on props (glasses, a hat, a
fake beard) and watch the box turn red and say **Unknown** when the recognizer
loses you. Take photos and email them to yourself.

All operator settings (RTSP URL, SMTP credentials, recognition tuning) live in a
separate **Admin** tab locked behind a username and password. The whole thing
runs in a Docker container.

## Features

- Configurable RTSP source (no camera-specific integration required)
- Live MJPEG video with face boxes drawn server-side
- Enroll a face by typing a name and clicking **Enroll my face**
- Real-time recognition; unrecognized faces are labelled **Unknown**
- Capture photos (stored on a Docker volume)
- Email selected photos to a user-supplied address via SMTP
- Admin-only settings tab protected by HTTP Basic auth
- SQLite + filesystem persistence on a Docker volume

## Quick start (prebuilt image, no build)

A multi-arch image (amd64 + arm64) is published to GitHub Container Registry, so
you can run Face Fun without compiling anything:

```bash
docker run -d --name face-fun \
  -p 8000:8000 \
  -e ADMIN_USERNAME=admin \
  -e ADMIN_PASSWORD=change-me \
  -v facefun-data:/data \
  ghcr.io/mo3he/face-fun:latest
```

Or with Docker Compose (pulls the published image instead of building):

```bash
cp .env.example .env   # set at least ADMIN_USERNAME / ADMIN_PASSWORD
docker compose pull
docker compose up -d
```

Then open:

- App: http://localhost:8000
- Admin: http://localhost:8000/admin (use your admin credentials)

## Build it yourself

```bash
cp .env.example .env
# edit .env and set at least ADMIN_USERNAME / ADMIN_PASSWORD
docker compose up --build
```

> The first build compiles `dlib`, so it takes a few minutes.

## Configuring the camera

Open **/admin**, log in, and set the RTSP URL. For Axis cameras this is usually:

```
rtsp://<user>:<password>@<camera-ip>/axis-media/media.amp
```

Saving a new RTSP URL automatically reconnects the stream.

## Configuring email (SMTP)

In **/admin**, fill in the SMTP host, port, username, password and from address.
Use the **Send a test email** form to verify it works. Port `465` uses implicit
SSL (uncheck STARTTLS); ports `587`/`25` use STARTTLS.

End users never see these settings; they only type their own destination email
on the main page when sending photos.

## How recognition works

- Faces are detected on a downscaled frame for speed, then matched against
  enrolled encodings using the `face_recognition` library.
- The **match tolerance** in admin controls strictness. Lower is stricter
  (default `0.6`). Raise it to be more forgiving of props, lower it to make the
  app lose you more easily.
- Detection runs every *N* frames (configurable) to keep CPU usage reasonable.

## Data & persistence

Everything is stored under `/data` inside the container, mounted to the
`facefun-data` Docker volume:

- `/data/facefun.db` - SQLite (enrolled faces + photo metadata)
- `/data/photos/` - captured JPEGs
- `/data/settings.json` - operator settings edited from the admin tab

## Running locally without Docker

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # needs cmake + a C++ toolchain for dlib
export DATA_DIR=./data ADMIN_USERNAME=admin ADMIN_PASSWORD=changeme
uvicorn app.main:app --reload
```

## Project layout

```
app/
  main.py         FastAPI app and routes
  config.py       Env config + persisted settings
  database.py     SQLite layer
  faces.py        In-memory encoding cache
  camera.py       RTSP capture + recognition worker
  email_utils.py  SMTP sending
  auth.py         Admin HTTP Basic auth
  templates/      index.html, admin.html
  static/         style.css, app.js, admin.js
Dockerfile
docker-compose.yml
```

## Security notes

- Change `ADMIN_USERNAME` / `ADMIN_PASSWORD` before deploying.
- Admin auth uses HTTP Basic, so put the app behind HTTPS (a reverse proxy) in
  production so credentials aren't sent in clear text.
- RTSP and SMTP credentials are stored in `settings.json` on the data volume;
  protect that volume accordingly.
