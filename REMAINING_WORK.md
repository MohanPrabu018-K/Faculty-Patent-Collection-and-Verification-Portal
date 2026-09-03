# Remaining Work — OCR.Space + FastAPI BackgroundTasks Migration

> Status: **COMPLETE (2026-08-31).** OCR.Space key configured locally; retry/backoff
> added (`OCRSPACE_MAX_RETRIES`/`OCRSPACE_BACKOFF_SECONDS`); real uvicorn
> BackgroundTasks upload→11-agent→PostgreSQL pipeline verified
> (`processing_status=AWAITING_REVIEW`, 12 job rows); Celery/Redis dead code removed;
> workflow diagram + PROJECT_BLUEPRINT + new README updated; backend 61 pytest pass;
> frontend production build pass; Playwright 17 tests pass (pipeline + auth + faculty).
> See the completion report / README for details. Sections below are the original plan,
> kept for history.

---

## 1. What Has Already Been Done (committed to working tree)

### 1.1 OCR.Space configuration
- [`backend/app/core/config.py`](backend/app/core/config.py:113) — added `OcrSpaceSettings` (`OCRSPACE_API_KEY`, `OCRSPACE_API_URL`, `OCRSPACE_LANGUAGE`, `OCRSPACE_OCR_ENGINE`, `OCRSPACE_TIMEOUT_SECONDS`) and instantiated `ocr_space_settings`.
- [`.env`](.env:34) — added `OCRSPACE_API_KEY=K8XXXXXXXXX` (placeholder — replace with real key).
- [`.env.example`](.env.example:34) — added the OCR.Space block with empty key.

### 1.2 OCR engine replaced (Tesseract → OCR.Space)
- [`backend/app/services/ocr_pipeline.py`](backend/app/services/ocr_pipeline.py:76) — `_ocr_image_bytes` now calls OCR.Space's `parse/image` endpoint via `httpx` (base64 image). Degrades gracefully when the API key is missing or the request fails.
- Added pure helpers `classify_document()` and `perform_ocr()` to [`backend/app/services/ocr_pipeline.py`](backend/app/services/ocr_pipeline.py:60) so agents no longer import from `workers/tasks.py`.

### 1.3 Celery → FastAPI BackgroundTasks
- [`backend/app/workers/orchestrator_task.py`](backend/app/workers/orchestrator_task.py:19) — replaced the `@celery_app.task` `process_document_task` with a plain `run_document_pipeline(file_path, ip_record_id)` function. Kept `process_document_task = run_document_pipeline` as a backward-compatible alias.
- [`backend/app/api/uploads.py`](backend/app/api/uploads.py:28) — added `background_tasks: BackgroundTasks` and schedule `run_document_pipeline` via `background_tasks.add_task(...)` instead of `.delay(...)`.
- [`backend/app/agents/classification_agent.py`](backend/app/agents/classification_agent.py:26) and [`backend/app/agents/document_understanding_agent.py`](backend/app/agents/document_understanding_agent.py:46) — import pure helpers from `ocr_pipeline` instead of `workers.tasks`.

### 1.4 Verification already run
- `python -m pytest tests -q` → **55 passed** (after fixing the `BackgroundTasks` parameter ordering).

---

## 2. Remaining Work To Complete

### 2.1 Replace the placeholder API key
Edit [`.env`](.env) and set:

```
OCRSPACE_API_KEY=<your real OCR.Space free API key>
```

The current value `K8XXXXXXXXX` is a placeholder. Without a valid key, OCR.Space requests will be rejected (the pipeline still degrades gracefully, but OCR text will be empty).

> **Free tier limits:** OCR.Space free key allows ~25,000 requests/month, 1 request every ~1–2 seconds, max ~1 MB per file, and 3 pages/PDF per request. For larger multi-page PDFs you must loop over pages (see §2.3).

### 2.2 Multi-page PDF handling (important)
The current `_ocr_image_bytes` sends one image per call. For a scanned multi-page PDF, the existing pipeline already rasterizes each page with PyMuPDF and calls OCR per page — so multi-page works. But **confirm** the free tier page limit (3 pages per call) is respected; the per-page loop already handles this naturally.

### 2.3 Add OCR.Space-specific retry / rate-limit handling
OCR.Space free tier can return HTTP 429 if called too fast. Add a small retry/backoff in `_ocr_image_bytes` around the `httpx.post` call (e.g., 3 attempts with 1s/2s backoff) if rate-limit failures occur in production.

### 2.4 Final end-to-end verification
Run these and confirm PASS:

```bash
# Backend unit tests
cd backend && python -m pytest tests -q

# Frontend build
cd frontend && npm run build

# Playwright (real browser E2E)
cd frontend && npx playwright test --project=chromium-desktop

# Real upload → 11-agent pipeline (no Celery now)
# 1. Login to get cookie
# 2. POST /api/v1/auth/csrf
# 3. POST /api/v1/uploads/ with the PDF + X-CSRF-Token header
# 4. Poll GET /api/v1/faculty/{record_id}/status until processing_status is terminal
#    Expected: AWAITING_REVIEW (verification VERIFICATION_REQUIRED) for test_patent.pdf
```

### 2.5 Remove now-dead Celery/Redis artifacts (safe cleanup only)
These are no longer required by the runtime, but **do not delete** until §2.4 passes:

- [`backend/app/workers/tasks.py`](backend/app/workers/tasks.py) — still contains `@celery_app.task` decorators and the old `process_qr_task` / `process_ocr_task` / `process_classification_task` / `process_extraction_task`. These are now unused (agents import from `ocr_pipeline`).
- [`backend/app/workers/__init__.py`](backend/app/workers/__init__.py) — still imports `redis`/`celery` and builds `celery_app`. This import chain is no longer needed by the app; but `main.py` does not import it. Verify nothing imports `app.workers` before removing.
- `RedisSettings` / `redis_settings` in [`backend/app/core/config.py`](backend/app/core/config.py:107) — still present and referenced by `get_settings()`; harmless to leave, but can be removed after confirming no imports.
- `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` in `.env` / `.env.example` — can remain (harmless) or be removed.

> **Rule:** do not remove Celery/Redis code until §2.4 confirms the BackgroundTasks pipeline is fully working, to avoid leaving a broken tree.

### 2.6 Update the workflow diagram
Regenerate or edit [`docs/workflow-diagram.svg`](docs/workflow-diagram.svg) to replace:
- "Celery Workers" → "FastAPI BackgroundTasks"
- "OCR (Tesseract)" → "OCR.Space (free API)"
- Remove/relabel Redis as cache/rate-limit only (no longer Celery broker).

### 2.7 Update documentation
Update `PROJECT_BLUEPRINT.md` / README (or add a changelog note) to record the OCR.Space + BackgroundTasks decision, the new env vars, and removal of the Celery/Redis dependency for processing.

---

## 3. Current Running State

- Backend: `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000` (Terminal 2)
- Frontend: `npm run dev -- --host` (Terminal 4)
- Celery worker: **stopped** (no longer required)
- PostgreSQL: localhost:5432
- Redis: localhost:6379 (still running, but not used for processing)

---

## 4. Blocking Notes / Honest Status

- The OCR.Space API key is still the placeholder `K8XXXXXXXXX`. A real key is required for actual OCR extraction.
- The full Playwright suite and the real upload E2E have **not** been re-run after the Celery→BackgroundTasks change. The backend unit tests (55) pass, but browser-level verification is outstanding.
- Celery/Redis removal is **not yet complete** (dead code remains in `workers/` and `config.py` by design until final verification passes).
