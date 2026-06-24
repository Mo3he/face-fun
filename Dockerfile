# Face Fun - dlib/face_recognition need a C++ toolchain to build, so we compile
# in a builder stage and copy the installed packages into a slim runtime image.
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        libopenblas-dev \
        liblapack-dev \
        libx11-dev \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt


FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    DATA_DIR=/data

# Runtime libraries needed by opencv/dlib (not the build toolchain).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libopenblas0 \
        liblapack3 \
        libgl1 \
        libglib2.0-0 \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

WORKDIR /app
COPY app ./app

RUN mkdir -p /data/photos
VOLUME ["/data"]

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
