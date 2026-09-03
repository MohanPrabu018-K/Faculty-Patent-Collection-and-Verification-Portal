# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# Production image for the Faculty Patent & Design Portal BACKEND.
#
# Why Docker (not Render's native Python runtime): the app needs OS packages
# that the native runtime cannot install:
#   - tesseract-ocr        (pytesseract — local OCR, the primary engine)
#   - libzbar0             (pyzbar — QR decoding)
#   - libgl1, libglib2.0-0 (opencv-python-headless runtime libs)
#
# Binds to 0.0.0.0:$PORT ($PORT is provided by Render; defaults to 8000 locally).
# No secrets are baked in — DATABASE_URL / SECRET_KEY / CORS_ORIGINS / etc. are
# supplied as runtime environment variables.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LOCAL_STORAGE_ROOT=/data/storage

# --- system packages (OCR + QR + OpenCV runtime + curl for healthcheck) ---
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      tesseract-ocr \
      tesseract-ocr-eng \
      libzbar0 \
      libgl1 \
      libglib2.0-0 \
      curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- Python dependencies (cached layer) ---
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install -r backend/requirements.txt

# --- application code + alembic config ---
COPY backend/ ./backend/
COPY alembic.ini ./alembic.ini

# --- non-root runtime user + writable upload dir ---
RUN useradd --create-home --uid 10001 appuser \
 && mkdir -p /data/storage \
 && chown -R appuser:appuser /app /data
USER appuser

# `app` is a namespace package under backend/, imported via the working dir.
WORKDIR /app/backend

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT:-8000}/healthz" || exit 1

# Shell form so ${PORT} expands. Render sets PORT; local `docker run` -> 8000.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-2} --proxy-headers --forwarded-allow-ips="*"
