# ChatGPT Continuation Prompt — Faculty Profile Portal

Paste the entire content below into ChatGPT to continue this project exactly where it stopped.

---

## Role

You are a senior full-stack software engineer working on a production-grade Faculty Profile Portal. Continue the work already in progress. Follow the project's existing constraints exactly. Do not rebuild, do not redesign, do not introduce paid services, do not weaken authentication/authorization.

## Project Location

```
e:/Faculty profile portal
```

## Project Overview

A free-first, institutional web portal that collects, verifies, organizes, and manages patents and design registrations associated with faculty.

- **Backend:** Python FastAPI + SQLAlchemy 2.0 (async + sync) + PostgreSQL 16
- **Frontend:** React 19 + TypeScript + Vite + TanStack Query + React Hook Form + Zod
- **Auth:** JWT in httpOnly `SameSite=Lax` cookie + CSRF double-submit
- **AI pipeline:** deterministic 11-agent orchestrator (no LLM required)
- **Original queue:** Celery + Redis
- **Migration in progress:** replacing Celery/Redis + Tesseract with **OCR.Space free API** + **FastAPI BackgroundTasks**

## Key Files

- Backend app factory: [`backend/app/main.py`](backend/app/main.py)
- Auth: [`backend/app/api/auth.py`](backend/app/api/auth.py), [`backend/app/api/deps.py`](backend/app/api/deps.py)
- Uploads: [`backend/app/api/uploads.py`](backend/app/api/uploads.py)
- OCR pipeline: [`backend/app/services/ocr_pipeline.py`](backend/app/services/ocr_pipeline.py)
- Pipeline runner (was Celery task): [`backend/app/workers/orchestrator_task.py`](backend/app/workers/orchestrator_task.py)
- Orchestrator: [`backend/app/ai_orchestrator.py`](backend/app/ai_orchestrator.py)
- Agents: [`backend/app/agents/`](backend/app/agents)
- Config: [`backend/app/core/config.py`](backend/app/core/config.py)
- Models: [`backend/app/models/base.py`](backend/app/models/base.py)
- Env: [`.env`](.env), [`.env.example`](.env.example)
- Remaining work: [`REMAINING_WORK.md`](REMAINING_WORK.md)
- Workflow diagram: [`docs/workflow-diagram.svg`](docs/workflow-diagram.svg)

## What Has Already Been Done

1. Added `OcrSpaceSettings` to `config.py` with fields:
   - `OCRSPACE_API_KEY`
   - `OCRSPACE_API_URL` (default `https://api.ocr.space/parse/image`)
   - `OCRSPACE_LANGUAGE` (default `eng`)
   - `OCRSPACE_OCR_ENGINE` (default `2`)
   - `OCRSPACE_TIMEOUT_SECONDS` (default `30`)

2. Added `OCRSPACE_*` values to `.env` and `.env.example`.

3. Replaced Tesseract OCR in `ocr_pipeline.py` `_ocr_image_bytes()` with an OCR.Space HTTP call (base64 image). It degrades gracefully when the API key is missing or the request fails.

4. Added pure helper functions `classify_document()` and `perform_ocr()` to `ocr_pipeline.py` (previously they were in `workers/tasks.py`).

5. Replaced the Celery task `process_document_task` with a plain function `run_document_pipeline(file_path, ip_record_id)` in `orchestrator_task.py`. A backward-compatible alias `process_document_task = run_document_pipeline` is kept.

6. Updated `uploads.py` to inject `background_tasks: BackgroundTasks` and schedule `run_document_pipeline` via `background_tasks.add_task(...)` instead of `.delay(...)`.

7. Updated `classification_agent.py` and `document_understanding_agent.py` to import helpers from `ocr_pipeline` instead of `workers.tasks`.

8. Stopped the Celery worker process.

9. Backend unit tests pass: `python -m pytest tests -q` → **55 passed**.

## What Still Needs To Be Done (in order)

### Step 1 — Real OCR.Space API key
The `.env` currently has a placeholder:
```
OCRSPACE_API_KEY=K8XXXXXXXXX
```
Replace `K8XXXXXXXXX` with the real OCR.Space free API key.

### Step 2 — OCR.Space rate-limit / retry handling
OCR.Space free tier can return HTTP 429. Add retry with backoff around the `httpx.post` call in `_ocr_image_bytes()` (e.g., 3 attempts, 1s/2s backoff, and treat 429 as retryable).

### Step 3 — Final verification
Run and confirm all pass:
```bash
# Backend tests
cd backend
python -m pytest tests -q

# Frontend build
cd ../frontend
npm run build

# Playwright browser E2E
npx playwright test --project=chromium-desktop
```
Then verify the real upload → 11-agent pipeline still works:
1. Login → cookie
2. `POST /api/v1/auth/csrf`
3. `POST /api/v1/uploads/` with `backend/test_patent.pdf` and `X-CSRF-Token` header
4. Poll `GET /api/v1/faculty/{record_id}/status` until terminal status.
   Expected for `test_patent.pdf`: `processing_status = AWAITING_REVIEW`, `verification_status = VERIFICATION_REQUIRED`.

### Step 4 — Remove dead Celery/Redis code (only after Step 3 passes)
- [`backend/app/workers/tasks.py`](backend/app/workers/tasks.py) — old Celery tasks now unused.
- [`backend/app/workers/__init__.py`](backend/app/workers/__init__.py) — Celery app + Redis monkeypatching no longer needed by runtime.
- `RedisSettings`/`redis_settings` in [`backend/app/core/config.py`](backend/app/core/config.py) — can remove if nothing imports them.
- `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` in `.env`/`.env.example` — can remove or leave (harmless).
- Remove `celery`/`redis` imports and the `@celery_app.task` decorators.

> Do NOT remove Celery/Redis code until the BackgroundTasks pipeline is verified working end-to-end.

### Step 5 — Update the workflow diagram
Regenerate/edit [`docs/workflow-diagram.svg`](docs/workflow-diagram.svg):
- Replace "Celery Workers" with "FastAPI BackgroundTasks".
- Replace "OCR (Tesseract)" with "OCR.Space (free API)".
- Relabel Redis as cache/rate-limit only (not the Celery broker).

### Step 6 — Update documentation
- Update `PROJECT_BLUEPRINT.md`/README with the OCR.Space + BackgroundTasks decision, new env vars, and removal of Celery/Redis processing dependency.

## Constraints (MUST follow)

- Do not add Ollama/LLM/paid APIs as a required dependency.
- Do not mock authentication or the 11-agent pipeline.
- Do not weaken authentication/authorization.
- Do not use Celery eager mode.
- Preserve the deterministic 11-agent processing.
- Keep the institutional restrained UI design.

## Current Running Services

- Backend: `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000` (cwd `backend`)
- Frontend: `npm run dev -- --host` (cwd `frontend`)
- PostgreSQL: localhost:5432
- Redis: localhost:6379 (still running, not used for processing)
- Celery worker: stopped

## Test Credentials

- Faculty A: `test@faculty.edu` / `TestPass123!`
- Faculty B: `faculty2@faculty.edu` / `TestPass456!`
- Admin: `admin@faculty.edu` / `AdminPass123!`

---

Begin by completing **Step 1** (you may need to ask the user for the real OCR.Space API key), then proceed through the remaining steps, running the affected tests after each change.
