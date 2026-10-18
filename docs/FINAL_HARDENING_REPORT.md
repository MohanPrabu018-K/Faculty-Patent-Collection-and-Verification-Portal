# Final Hardening Report — Python E2E Guard, API Config Audit, OCR Dependency

Date: 2026-10-11
Scope: follow-up hardening after release QA workstreams 2H–2K. No production
contact, no database mutation, no real uploads, no secrets touched. Everything
below was performed locally.

---

## 1. Files changed and why

### `scripts/staging/guard.py` (modified — additive only)
Extended the single source-of-truth fail-closed guard with the API/hosted-target
half that previously existed only on the frontend side (`frontend/tests-staging/
guard.ts`) so Python entry points and Playwright agree on what a safe target is.
No existing function or constant was changed; new additions only:

* `require_staging_confirm(context)` — requires `STAGING_CONFIRM=1`.
* `assert_staging_api_url(label, url)` / `api_host_of()` / `is_loopback_api_host()` /
  `is_api_production_host()` / `_api_host_allowlist()` — loopback always allowed;
  the two known production hosts **and** the whole `.pages.dev` / `.onrender.com`
  namespaces always refused (even if allow-listed); any other non-loopback host
  requires an exact `STAGING_ALLOWED_HOSTS` entry.
* `resolve_staging_api_url(...)` — requires explicit confirmation + a valid URL;
  never falls back to a default or to production.
* `sandboxed_backend_env(...)` — builds the ONLY environment a spawned backend
  subprocess may inherit: `DATABASE_URL`/`STAGING_DATABASE_URL` pinned to a
  validated disposable target, parent remote-opt-in/allowlist tokens stripped,
  and non-production run flags pinned (`APP_ENV=development`, `E2E_TEST=1`,
  `SCHEDULER_ENABLED=false`, `COOKIE_SECURE=false`).

### `scripts/e2e_backgroundtasks_pipeline.py` (modified)
**Original risk:** launched `uvicorn app.main:app` with `{**os.environ, ...}`,
inheriting any ambient `DATABASE_URL` and the repo-root `.env` (the app loads it
at import), then performed a real upload + DB writes. A leftover production DSN
could have routed the run to production.

**Guard added (before any side effect):**
1. `guard.require_staging_confirm(...)` — aborts without `STAGING_CONFIRM=1`.
2. `guard.resolve_staging_database_url()` — `STAGING_DATABASE_URL` required and
   validated disposable/loopback; `DATABASE_URL` is never consulted.
3. `guard.sandboxed_backend_env(staging_db_url, backend_dir=...)` — the child
   gets `DATABASE_URL` force-set to the validated target, so the root `.env`
   value (and any ambient DSN) can never leak into the subprocess; remote
   opt-in tokens are dropped; non-production flags pinned.

Docstring updated with a runnable example.

### `scripts/verify_real_upload_459641.py` (modified)
**Original risk:** hardcoded `BASE = "http://localhost:8000"` and uploaded a real
certificate to whatever backend happened to be listening there — if that backend
was connected to production, the real PDF + extracted PII would land in
production.

**Guard added (before any network call):**
1. `guard.resolve_staging_api_url()` — requires `STAGING_CONFIRM=1` **and** an
   explicit `STAGING_API_URL`. Loopback is allowed; the production hosts and
   `.pages.dev`/`.onrender.com` namespaces are refused; any other host must be
   in `STAGING_ALLOWED_HOSTS`. There is no default target.

Docstring updated with a runnable example. Script functionality is otherwise
unchanged.

### `scripts/staging/test_api_guard.py` (new)
23 focused, dependency-free tests covering unsafe targets, missing/malformed
configuration, production refusal (host + suffix + allowlist-bypass attempts),
loopback acceptance, `resolve_staging_api_url` no-default behavior, and
`sandboxed_backend_env` override/strip semantics. Never touches a DB or socket.

### `scripts/check_ocr_deps.py` (new)
Safe availability probe for the local OCR engine (see §3). No documents opened,
no network, no writes.

### `README.md` (modified — narrow doc correction)
The `Architecture`, upload-flow, Configuration, and Prerequisites sections
claimed "OCR is the OCR.Space API" and "no Tesseract". The code is local-first
(PyMuPDF text → optional PaddleOCR → Tesseract → optional OCR.Space fallback), so
those claims were factually wrong. Updated to describe the real chain, the
`TESSERACT_CMD` / `OCRSPACE_FALLBACK_ENABLED` settings, and a pointer to
`scripts/check_ocr_deps.py`.

### Unchanged (verified)
`frontend/playwright-staging.config.ts`, `frontend/tests-staging/` (incl.
`guard.ts` + `00-guard.spec.ts`), `backend/tests/conftest.py`, all pre-existing
`scripts/staging/` tooling behaviour, and the frontend legacy config guards from
2H remain in place. The two hardened scripts were NOT executed during
inspection or hardening.

---

## 2. Frontend API configuration audit (secret-safe)

Result: **local/loopback** — no remote target is configured anywhere in the repo.

* `frontend/.env`, `frontend/.env.local`, `frontend/.env.production`: **absent**.
  Only the template `frontend/.env.production.example` exists (key on
  `VITE_API_BASE_URL`, build-time, comments only — no values inspected).
* With no env file, `frontend/src/api/client.ts` falls back to its default:
  `http://localhost:8000/api/v1` (loopback).
* All executable legacy Playwright configs (`playwright.config.ts`,
  `playwright-e2e.config.ts`, `playwright-exact.config.ts`) and the gitignored
  `playwright-hardening.tmp.ts` apply `guardedDevWebServer` + `resolveLegacyEnv`
  (verified by read-through; legacyLoopback vitest suite 50/50 green, §4).
* Vite gives existing process environment precedence over `.env` files, and
  `guardedDevWebServer` pins `env.VITE_API_BASE_URL` to a loopback URL, so even a
  stray `frontend/.env` cannot make the browser target a remote API.
* The staging Playwright config (`resolveStagingEnv`) and the Python/DB guards
  remain fail-closed and unchanged.
* No production/staging secret values were read, printed, copied, or committed.

---

## 3. OCR dependency findings and setup instructions

**Finding (corrects the 2K report):** the 2K report's statement "Tesseract is not
installed (`tesseract_on_path: False`)" was based on a PATH-only probe. In fact
Tesseract **is installed and wired** on this machine:

* `tesseract v5.5.3.20260724` at `C:\Program Files\Tesseract-OCR\tesseract.exe`
  (not on `PATH`, but reachable via `TESSERACT_CMD`, which is set in the repo-root
  `.env`).
* `backend/app/services/ocr_pipeline.py::_resolve_tesseract_cmd()` resolves it
  exactly this way (`TESSERACT_CMD` → `PATH` → common install dirs) — verified
  programmatically: `resolved_cmd == 'C:\\Program Files\\Tesseract-OCR\\tesseract.exe'`.
* `pytesseract 0.3.13` is present in the backend venv and successfully invokes the
  binary (`pytesseract.get_tesseract_version() → 5.5.3.20260724`).

The pipeline is local-first: PyMuPDF embedded text → optional PaddleOCR →
**Tesseract (the guaranteed-local engine)** → optional **OCR.Space** fallback
(only consulted when local engines produce no text *and* `OCRSPACE_FALLBACK_ENABLED`
is true and a key is configured). The OCR.Space key currently configured in the
repo-root `.env` is the documented placeholder (no real credentials present), so
the external fallback is effectively inert and the portal runs fully offline on
local OCR. The previous real-document run's reliance on the external fallback was
an environment-probe artifact, not a code path requirement.

**Setup instructions** (already documented in `docs/DEPLOYMENT.md`, now also in
README):
* Windows: `winget install UB-Mannheim.TesseractOCR` (or set `TESSERACT_CMD` to an
  existing binary, e.g. `C:\Program Files\Tesseract-OCR\tesseract.exe`).
* Debian/Ubuntu: `sudo apt-get install -y tesseract-ocr tesseract-ocr-eng`.
* macOS: `brew install tesseract`.
* Verify: `python scripts/check_ocr_deps.py` (exit 0 when available; this machine
  now reports OK).
* Optional: set `OCRSPACE_FALLBACK_ENABLED=false` to disable the external fallback
  entirely. Leave `OCRSPACE_API_KEY` empty to stay fully offline.

No OCR provider behaviour was changed; fallbacks were not removed.

---

## 4. Verification performed (all local)

| Command | Result |
|---------|--------|
| `backend\.venv\Scripts\python.exe -m pytest scripts/staging -q` | **42 passed** (existing DB guard 19 + new API/env guard 23), 0 skipped |
| `python -m py_compile scripts/e2e_backgroundtasks_pipeline.py scripts/verify_real_upload_459641.py scripts/staging/guard.py scripts/staging/test_api_guard.py` | OK (exit 0) |
| `npx vitest run src/testing/legacyGuard.test.ts` (frontend) | **50 passed** |
| `python scripts/check_ocr_deps.py` (backend venv) | OK — Tesseract 5.5.3 found, pytesseract invokes it |

Not run in this execution (correctly out of scope / needing a live stack): the two
hardened scripts themselves, the backend pytest suite, and the staging/e2e
Playwright suites. They were exercised in 2H–2K and none of their code was
modified here (backend untouched; `scripts/staging/` guard additions only). The
frontend full vitest suite (136/136) and the staging suites were established in
2H–2K and are unchanged.

---

## 5. Remaining risks and limitations

* **Operator discipline for `verify_real_upload_459641.py`:** the guard controls
  the API address (confirmed, non-production) but cannot verify which database the
  already-running backend itself is connected to. The docstring states this
  explicitly; the operator must point the backend at a disposable stack.
* **App-side production-DB guard:** there is still no backend-side guard refusing a
  production DSN when `APP_ENV=staging`; the fail-closed check lives in the staging
  tooling. Pre-existing, documented in `docs/STAGING_PROVISIONING_INVESTIGATION.md`,
  out of scope here.
* **`TESSERACT_CMD` is machine-wired via `.env`:** on another machine without
  Tesseract (or without `TESSERACT_CMD`), scanned-page OCR falls through to the
  external fallback (which is inert here because only the placeholder key exists).
  `scripts/check_ocr_deps.py` surfaces this immediately.
* **Hardcoded test credentials** (`test@faculty.edu` / `TestPass123!`) remain in both
  scripts; they target seeded disposable stacks only and are refused for any
  unconfirmed target.
* **Reported, not fixed:** the repo-root `.env` still contains the placeholder
  OCR.Space key; installing a real key or deleting the entry is a user decision.
* **Cleanup:** no run rows, files, or master records were created by this work;
  `backend\storage\` untouched; no commits/pushes/deploys; production never
  contacted.