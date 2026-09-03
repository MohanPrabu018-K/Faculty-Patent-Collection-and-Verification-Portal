# Deployment Guide — Faculty Patent & Design Collection and Verification Portal

This document describes how to deploy the portal to production. It contains **no
secret values** — every secret is supplied at deploy time as an environment
variable / platform secret.

---

## 1. Architecture

```
┌─────────────────────────┐        HTTPS + cookies         ┌──────────────────────────┐
│  Frontend (static SPA)  │  ───────────────────────────▶  │  Backend (FastAPI/uvicorn)│
│  React 19 + Vite build  │   fetch(VITE_API_BASE_URL)      │  in-process 11-agent      │
│  served as static files │  ◀───────────────────────────  │  pipeline (BackgroundTasks)│
└─────────────────────────┘   JSON + Set-Cookie (Secure)    └────────────┬─────────────┘
                                                                          │ asyncpg (TLS)
                                                             ┌────────────▼─────────────┐
                                                             │  PostgreSQL 16 (managed) │
                                                             │  Neon — single source    │
                                                             │  of truth + Alembic      │
                                                             └──────────────────────────┘
```

* **No Redis, no Celery, no message queue.** The document pipeline runs in the
  backend process via FastAPI `BackgroundTasks`, so the backend **must be a
  long-running process** (a normal web service / VM / container) — **not** a
  serverless function that freezes after returning the HTTP response.
* **Local files:** uploaded documents are written under `LOCAL_STORAGE_ROOT`
  (`./storage` by default). Use a persistent disk/volume, or set
  `STORAGE_BACKEND=s3` if you wire an object store (not required).
* **OCR:** local-first — PyMuPDF embedded text → Tesseract (must be installed on
  the backend host) → OCR.Space (optional external fallback, disabled by leaving
  `OCRSPACE_API_KEY` empty). The portal is fully functional with local OCR only.

---

## 2. Prerequisites

| Component | Requirement |
|---|---|
| Backend host | Python **3.11+** (3.12 recommended), a persistent process, outbound HTTPS |
| Backend host packages | **Tesseract OCR** (`tesseract` on `PATH`, or set `TESSERACT_CMD`), **libzbar** (for `pyzbar` QR); `poppler`/none extra for PyMuPDF |
| Frontend build | Node.js **20+** |
| Database | PostgreSQL **16**, TLS-capable. A Neon free project works. |
| TLS | HTTPS termination in front of both frontend and backend (platform-provided or a reverse proxy). |

Install backend deps (native / VM):

```bash
cd backend
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt                   # runtime deps (kept in sync with pyproject.toml)
pip install -e ".[dev]"                            # ONLY if you also want to run the test suite (needs a [build-system] — see note below)
```

> `pyproject.toml` currently has no `[build-system]`/package config, so
> `pip install .` / `-e .` will not build a wheel. Runtime installs use
> `backend/requirements.txt`; the app is imported as a namespace package with
> `backend/` on `sys.path` (which is how uvicorn and pytest already run it).

### Docker / Render (recommended — provides Tesseract + libzbar)

A production `Dockerfile` (repo root) and `render.yaml` blueprint are included.
The image is `python:3.12-slim` + `tesseract-ocr`, `tesseract-ocr-eng`,
`libzbar0`, `libgl1`, `libglib2.0-0`, then `pip install -r backend/requirements.txt`.
It binds `0.0.0.0:$PORT` and runs as a non-root user. See §9 for Render settings.

Install Tesseract:

```bash
# Debian/Ubuntu
sudo apt-get update && sudo apt-get install -y tesseract-ocr libzbar0
# macOS
brew install tesseract zbar
# Windows (host)
winget install UB-Mannheim.TesseractOCR
```

---

## 3. Environment variables

Set these on the **backend** as platform secrets / env vars. Do **not** ship a
`.env` file to production — `.env` is for local development only and is
gitignored. Full annotated list: [`.env.example`](../.env.example).

### Required in production

| Variable | Example / note |
|---|---|
| `APP_ENV` | `production` — turns on the safety guards in §12 |
| `SECRET_KEY` | 48+ random chars. **Signs the JWT and CSRF token.** Generate: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `DATABASE_URL` | `postgresql+asyncpg://USER:PASSWORD@HOST/DB?sslmode=require` — the hosted DB. `sslmode`/`channel_binding` params are fine; the app strips them for asyncpg and enforces TLS for non-local hosts. |
| `CORS_ORIGINS` | The exact public frontend origin, e.g. `https://portal.example`. Comma-separate multiple. **Must not be `*`** (credentials are used). |
| `COOKIE_SECURE` | `true` (HTTPS required) |
| `COOKIE_SAMESITE` | `lax` if the frontend and API share a site; **`none`** if they are on different domains (requires `COOKIE_SECURE=true`) |
| `DEBUG` | `false` |

If `APP_ENV` is `production`/`staging`/`prod`/`release` and any of the above is a
dev placeholder (`SECRET_KEY` containing `dev-*`/`change-me`, `COOKIE_SECURE`
false, `CORS_ORIGINS` `*` or localhost-only, `DATABASE_URL` at `@localhost` or
`change-me`) the backend **refuses to start** with a clear error. This is by
design.

### Optional (have safe defaults)

| Variable | Default | Note |
|---|---|---|
| `JWT_ACCESS_TOKEN_MINUTES` | `30` | 5–1440 |
| `TESSERACT_CMD` | auto-detect | explicit path if Tesseract isn't on `PATH` |
| `TESSERACT_LANGS` | `eng` | |
| `OCRSPACE_FALLBACK_ENABLED` / `OCRSPACE_API_KEY` | `true` / *(empty)* | leave the key empty to run OCR fully offline |
| `IPINDIA_ENABLED` / `IPINDIA_SEARCH_URL` | `false` / *(empty)* | no official free API — verification stays **manual** unless you point this at an InPASS proxy |
| `MAX_UPLOAD_BYTES` | `20971520` (20 MB) | |
| `LOCAL_STORAGE_ROOT` | `./storage` | put on a persistent volume |
| `RATE_LIMIT_*`, `ACCOUNT_LOCKOUT_*` | see `.env.example` | |

> `JWT_SECRET` in `.env.example` is **not read** by the app — tokens are signed
> with `SECRET_KEY`.

### Frontend build variable

| Variable | Note |
|---|---|
| `VITE_API_BASE_URL` | Public HTTPS URL of the API **including `/api/v1`**, e.g. `https://api.portal.example/api/v1`. Baked into the static bundle at build time. Template: [`frontend/.env.production.example`](../frontend/.env.production.example). If unset, the bundle falls back to `http://localhost:8000/api/v1` (dev only). |

---

## 4. Database setup

The schema is managed by **Alembic**. `alembic.ini` lives at the **repo root** and
its `env.py` reads the real connection string from `app.core.database` (i.e. from
`DATABASE_URL`); the `sqlalchemy.url` in `alembic.ini` is only a non-secret local
fallback.

```bash
# from the repo root, with DATABASE_URL exported (or a local .env present)
cd "<repo root>"
python -m alembic -c alembic.ini current      # show applied revision
python -m alembic -c alembic.ini heads         # show latest revision
python -m alembic -c alembic.ini history       # full history
```

Current state of this repo: **`005 (head)` — schema up to date, no pending
migrations.** On a brand-new database:

```bash
python -m alembic -c alembic.ini upgrade head
```

Then seed the first Super Admin (idempotent):

```bash
cd backend && python create_test_users.py       # creates admin@faculty.edu / AdminPass123!
```

**Change that password immediately** after first login (Admin → Faculty → the
admin's own row, or reset-credentials). For a real institution, create the real
Super Admin and delete the seed accounts.

> Never run `downgrade`, `--sql` destructive DDL, or drop/reset against a
> populated production database.

---

## 5. Migration command (deploy hook)

Run **once per deploy, before starting the new backend**:

```bash
python -m alembic -c alembic.ini upgrade head
```

If it prints nothing to apply: **schema already up to date** — safe to continue.

---

## 6. Backend start command

```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2
```

* `--workers 2` (or more) is fine — the pipeline runs per-request via
  `BackgroundTasks`, no shared in-process state between workers except the
  in-memory rate-limiter and export-job cache (acceptable; see §16 limitations).
* Behind a reverse proxy, pass `--proxy-headers --forwarded-allow-ips="*"` (or a
  specific proxy IP) so client IPs and the HTTPS scheme are honoured.
* Health check: `GET /healthz` → `{"status":"ok"}` (also `/readyz`).

Process managers: `systemd` unit, a container `CMD`, or a platform "web service".
Example `Procfile` (Render/Railway/Heroku-style):

```
release: python -m alembic -c alembic.ini upgrade head
web: cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 2
```

---

## 7. Frontend build command

```bash
cd frontend
npm ci
VITE_API_BASE_URL="https://api.portal.example/api/v1" npm run build
# output: frontend/dist/  (static files)
```

`npm run build` also runs `tsc -b` (type-check) and fails on TS errors.

---

## 8. Frontend deployment

`frontend/dist/` is a plain static site. Deploy to any static host
(Cloudflare Pages, GitHub Pages, Netlify, Vercel static, S3+CloudFront, nginx…).

* Set the build command to `npm run build` and the publish directory to
  `frontend/dist`, with `VITE_API_BASE_URL` in the build environment.
* **SPA fallback:** configure the host to serve `index.html` for any unknown
  path (client-side routing). Examples:
  * Netlify `_redirects`: `/*  /index.html  200`
  * Cloudflare Pages: automatic for SPAs
  * nginx: `try_files $uri /index.html;`
* No server-side rendering, no Node runtime needed at serve time.

---

## 9. Backend deployment

Deploy the API as a long-running web service.

### Render (Docker) — using the committed blueprint

`Dockerfile` (repo root) + `render.yaml` are ready. In Render:

| Render setting | Value |
|---|---|
| Service type | **Web Service** |
| Language / Runtime | **Docker** |
| Dockerfile path | `./Dockerfile` |
| Docker build context | `.` (repo root) |
| Build command | *(leave blank — the Dockerfile is the build)* |
| Start command | *(leave blank — the Dockerfile `CMD` runs `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers $WEB_CONCURRENCY --proxy-headers`)* |
| Pre-Deploy Command | `alembic -c /app/alembic.ini upgrade head` |
| Health Check Path | `/healthz` |
| Instance type | `free` (spins down when idle, no disk) or `starter` (always-on, disk-capable) |

**Environment variables (names only — set values in the dashboard):**

| Name | Source |
|---|---|
| `SECRET_KEY` | Render **Generate** (blueprint uses `generateValue: true`) |
| `DATABASE_URL` | dashboard secret — the Neon `postgresql+asyncpg://…?sslmode=require` URL |
| `CORS_ORIGINS` | dashboard — the deployed **Static Site** URL (e.g. `https://faculty-portal-web.onrender.com`) |
| `APP_ENV` | `production` (in blueprint) |
| `DEBUG` | `false` (in blueprint) |
| `COOKIE_SECURE` | `true` (in blueprint) |
| `COOKIE_SAMESITE` | `none` (in blueprint — frontend on a different domain) |
| `WEB_CONCURRENCY` | `2` (in blueprint) |
| `LOCAL_STORAGE_ROOT` | `/data/storage` (in blueprint; **ephemeral on free** — see §13 / limitations) |
| `JWT_ACCESS_TOKEN_MINUTES` | `30` (in blueprint) |
| `OCRSPACE_API_KEY` | dashboard, **optional** — leave unset to run OCR fully offline |
| `IPINDIA_ENABLED` / `IPINDIA_SEARCH_URL` | optional; leave default (verification stays manual) |

`PORT` is injected by Render automatically — do not set it.

After the first successful deploy, open the service **Shell** and seed the first
admin once: `python create_test_users.py` — then log in as `admin@faculty.edu`
and change the password immediately.

### VM / bare host (alternative)

`systemd` service running the §6 uvicorn command, `apt-get install -y
tesseract-ocr tesseract-ocr-eng libzbar0`, nginx/Caddy for TLS, a persistent
`LOCAL_STORAGE_ROOT`. Run `alembic -c alembic.ini upgrade head` (repo root) as the
pre-start / release step.

---

## 10. CORS configuration

* Backend reads `CORS_ORIGINS` (comma-separated or JSON array) and allows exactly
  those origins with `allow_credentials=true`.
* **Production must not use `*`** — the guard rejects it. List every frontend
  origin that will call the API (apex + `www`, staging, etc.).
* Local dev origins (`http://localhost:5173`, `:4173`, `127.0.0.1`) may stay in
  `CORS_ORIGINS` for non-production `APP_ENV`; they're harmless but should be
  dropped from the production value.

---

## 11. HTTPS requirements

* Both the frontend and the API **must** be served over HTTPS in production.
* `COOKIE_SECURE=true` (enforced) means auth cookies are only sent over HTTPS —
  the app is unusable over plain HTTP in production, by design.
* If the frontend and API are on **different domains**, set
  `COOKIE_SAMESITE=none` (with `COOKIE_SECURE=true`) so the browser sends the
  session + CSRF cookies on cross-site XHR.
* Terminate TLS at the platform LB or a reverse proxy; forward
  `X-Forwarded-Proto`/`X-Forwarded-For` and start uvicorn with `--proxy-headers`.

---

## 12. Secret configuration

* Provide `SECRET_KEY`, `DATABASE_URL` (and `OCRSPACE_API_KEY` if you use the
  external OCR fallback) as **platform secrets / environment variables** — never
  in the repo, the frontend bundle, an API response, or logs.
* `.env` is gitignored and development-only. `.env.example` and
  `frontend/.env.production.example` are templates with placeholder values only.
* The app never returns secrets: `/api/v1/admin/settings` exposes capability
  status (OCR/QR/verification enabled/disabled) but not the DB URL, JWT secret,
  or OCR key. `password_hash` is stripped from all serializers.
* Production-start guards (`APP_ENV=production|staging|prod|release`):
  * `SECRET_KEY` must not contain `change-me` / `dev-secret` / `dev-jwt` /
    `insecure` / `example` and must be ≥ 32 chars.
  * `COOKIE_SECURE` must be `true`.
  * `CORS_ORIGINS` must not contain `*` and must include a non-localhost origin.
  * `DATABASE_URL` must not be `@localhost` / contain `change-me`.
  A violation aborts startup with an explicit message.
* **Rotating `SECRET_KEY` invalidates all existing sessions** (users must log in
  again). That is acceptable and expected for a rotation.

---

## 13. Backup requirements

The production database is **managed PostgreSQL (Neon)**. Backups are a
provider-side setting and **cannot be configured from this repository**:

1. In the Neon project console, confirm **Point-in-Time Restore** is enabled and
   note the retention window (24 h on the free tier; up to 30 days on paid).
   Increase retention for production.
2. Optionally add an out-of-provider dump on a schedule (host cron / CI):

   ```bash
   pg_dump "$DATABASE_URL_PSQL" --format=custom --file "portal-$(date +%F).dump"
   # DATABASE_URL_PSQL = the same URL with the +asyncpg driver removed:
   #   postgresql://USER:PASSWORD@HOST/DB?sslmode=require
   ```

   Store the dump in object storage with lifecycle expiry. Test a restore into a
   scratch database quarterly.
3. If you migrate off Neon, replicate the equivalent PITR + off-site dump
   arrangement on the new provider.

No automated backup job is committed — this is a documented operational
requirement, not code.

---

## 14. Health check

| Endpoint | Expected | Use |
|---|---|---|
| `GET /healthz` | `200 {"status":"ok"}` | liveness / LB health |
| `GET /readyz` | `200 {"status":"ready"}` | readiness |
| `GET /metrics` | `200` service info JSON | basic monitoring |

Point the platform health check at `/healthz`.

---

## 15. Production smoke tests

After each deploy, against the live URLs:

```bash
# 1. Backend up
curl -fsS https://api.portal.example/healthz            # -> {"status":"ok"}

# 2. Unauthenticated is rejected
curl -s -o /dev/null -w '%{http_code}\n' \
     https://api.portal.example/api/v1/auth/me           # -> 401

# 3. Login (returns access_token + csrf_token; also sets Secure cookies)
curl -s -c cj.txt -X POST https://api.portal.example/api/v1/auth/login \
     -H 'Content-Type: application/json' \
     -d '{"email":"admin@faculty.edu","password":"<the admin password>"}' \
     -w '\nHTTP %{http_code}\n'
grep -i 'Secure' cj.txt && echo "cookies are Secure ✓"

# 4. Authenticated call works (cookie jar)
curl -s -b cj.txt https://api.portal.example/api/v1/auth/me -w '\nHTTP %{http_code}\n'
```

Then in a browser at `https://portal.example`:

* Login as Super Admin → Dashboard, Faculty, Granted Patents, upload a test PDF →
  poll to `AWAITING_REVIEW` → open the record → correct a field → Reports → CSV
  export downloads → Excel import preview → Audit → Settings.
* Login as an HOD → confirm **only their department's** faculty / documents /
  duplicates / conflicts / audit are visible; `/admin/*` returns 403.
* Login as a Faculty member → dashboard, profile, upload, history, search
  (own records only), associations, notifications; `/admin/*` and `/hod/*`
  return 403.
* Browser console: **0 exceptions**, **0 CORS failures**, **0 mixed-content**,
  **0 config-caused auth failures**.
* Resize to 375 / 768 / 1024 / 1440 px — no horizontal page scroll; tables scroll
  inside their own container.

Backend test suite (CI, not against prod DB unless intended):

```bash
cd backend && python -m pytest tests -q            # 96 passing
```

---

## 16. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Backend exits on start with `SECRET_KEY is a development placeholder` / `COOKIE_SECURE must be true` / `CORS_ORIGINS must not contain '*'` / `DATABASE_URL points at localhost` | `APP_ENV` is a production value but that env var is still a dev default. Set the real value. |
| `error parsing value for field "cors_origins"` | Old build. Current code accepts `a, b` **or** `["a","b"]`; redeploy. |
| Browser: `No 'Access-Control-Allow-Origin'` on API calls | The frontend origin isn't in `CORS_ORIGINS`, **or** a request failed the CSRF middleware (which runs before CORS): ensure the SPA sends `X-CSRF-Token` equal to the `csrf_token` cookie on POST/PUT/PATCH/DELETE (the bundled client does this automatically). |
| Login succeeds but the next request is 401 | Cross-domain frontend/API without `COOKIE_SAMESITE=none` + `COOKIE_SECURE=true`, or the frontend not sending `credentials: 'include'` (the bundled client does). |
| `401` on every authenticated request after a deploy | `SECRET_KEY` changed → all sessions invalidated; users must log in again. Don't change it unless you mean to. |
| Uploads reach `FAILED` immediately with "File not found" | `LOCAL_STORAGE_ROOT` is on ephemeral storage that the worker can't see. Use a persistent volume shared by the process. |
| OCR text always empty / `ocr_engine: none` | Tesseract not installed on the backend host or not on `PATH`. Install it or set `TESSERACT_CMD`. |
| Verification never becomes `VERIFIED` | Expected — `IPINDIA_ENABLED=false` and there is no automated IP‑India lookup; records go to `VERIFICATION_REQUIRED` / manual. Not a bug. |
| `alembic` says `No 'script_location' key` | Run it from the **repo root** with `-c alembic.ini`, not from `backend/`. |
| Search feels slow (~1–2 s/page) | Neon network latency + per-page joins. Acceptable; add a Postgres FTS/trigram index if needed. Do not add Redis/a search engine for this. |

---

## Known operational limitations (see also the BATCH 6 report)

* **Rate-limiter and export-job store are in-process.** With multiple uvicorn
  workers, rate limits are per-worker and an export job created on worker A can't
  be downloaded via worker B until re-created. Fine for a single institution's
  load; move to a shared store (Redis/DB) only if you scale out aggressively.
* **Audit `ip_address`** is not captured (always shown as "—"); actor
  name/role/department are resolved. Capturing IPs would require threading the
  request into every `log_audit()` call.
* **Verification is manual** by design (no free IP‑India API).
* Some legacy `verification_attempt.result` rows written before a serialization
  fix hold a Python‑repr string; only shown inside a collapsed "Technical
  details" panel.
