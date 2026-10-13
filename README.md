# Faculty Patent Collection Portal

Institutional web portal that collects, verifies, organizes, and manages faculty
**patents and design registrations**. Free-first, no Docker, no mandatory paid APIs.

> **AI assists. Rules validate. Evidence supports. Humans confirm uncertainty.
> The database stores controlled results.**

See [`PROJECT_BLUEPRINT.md`](PROJECT_BLUEPRINT.md) for the full master reference.

## Architecture (current)

| Layer | Choice |
|-------|--------|
| API | FastAPI + Pydantic v2 (async), SQLAlchemy 2.0 + Alembic |
| Database | PostgreSQL 16 — single source of truth |
| Document processing | **FastAPI `BackgroundTasks`** — the deterministic 11-agent pipeline runs in-process (no Celery, no Redis, no queue) |
| OCR | **Local-first**: PyMuPDF embedded text → PaddleOCR (optional) → **Tesseract** (local, open-source; set `TESSERACT_CMD` if not on `PATH`) → OCR.Space (optional external fallback, HTTP-429 retry/backoff, degrades gracefully when unset/failing) |
| QR | `pyzbar` (OpenCV fallback) |
| PDF | PyMuPDF + pdfplumber |
| Frontend | React 18 + TypeScript + Vite |
| Auth | Argon2id + JWT httpOnly SameSite cookie + double-submit CSRF |

### Upload → processing flow

```
POST /api/v1/uploads/  →  IpRecord/IpFile/ProcessingJob rows (status QUEUED)
                       →  background_tasks.add_task(run_document_pipeline, ...)
                       →  202 Accepted
run_document_pipeline  →  AIOrchestrator.execute()  →  11 deterministic agents:
   1 Classification · 2 QR · 3 OCR Extraction (local-first: Tesseract) · 4 Understanding
   5 Verification · 6 Identity · 7 Duplicate · 8 Conflict
   9 Association · 10 Data Quality · 11 Analytics
                       →  persist extracted fields + ProcessingJob rows to PostgreSQL
                       →  processing_status: COMPLETED | COMPLETED_WITH_ERRORS
                                             | AWAITING_REVIEW | FAILED
GET /api/v1/uploads/{id}/status  →  UI polls until terminal status
```

## Configuration

Copy `.env.example` to `.env` and fill in values. Local OCR block:

```
TESSERACT_CMD=                 # optional: explicit path if tesseract is not on PATH
                              # (e.g. C:\Program Files\Tesseract-OCR\tesseract.exe)
TESSERACT_LANGS=eng
OCRSPACE_FALLBACK_ENABLED=true # set false to disable the external fallback entirely
```

OCR.Space (optional external fallback) block:

```
OCRSPACE_API_KEY=            # free key from https://ocr.space/ocrapi  (configure locally; do not commit)
OCRSPACE_API_URL=https://api.ocr.space/parse/image
OCRSPACE_LANGUAGE=eng
OCRSPACE_OCR_ENGINE=2
OCRSPACE_TIMEOUT_SECONDS=30
OCRSPACE_MAX_RETRIES=3        # retry HTTP 429 / transient failures
OCRSPACE_BACKOFF_SECONDS=2.0  # linear backoff * attempt
```

Leave `OCRSPACE_API_KEY` empty to run fully offline: the local engines still OCR
scanned pages, and without a fallback key the pipeline records a warning instead
of making an external call.

## Running (native, no Docker)

Prerequisites: Python 3.12, Node.js 20+, PostgreSQL 16, libzbar. **No Redis, no
Celery.** OCR is local-first: install Tesseract for scanned PDFs (see
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)) or set `TESSERACT_CMD` to an
existing binary — run `python scripts/check_ocr_deps.py` to verify availability.

```bash
# Backend
cd backend
python -m venv .venv && . .venv/Scripts/activate   # bash: source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head

# Two processes
uvicorn app.main:app --reload      # runs the BackgroundTasks pipeline in-process
cd ../frontend && npm install && npm run dev
```

## Tests

```bash
cd backend && python -m pytest tests -q          # unit / contract / agent tests
python scripts/e2e_backgroundtasks_pipeline.py   # real upload → 11-agent → PostgreSQL E2E (needs live DB + seeded users)
cd frontend && npm run build                     # production build
cd frontend && npx playwright test               # browser E2E (if configured)
```
