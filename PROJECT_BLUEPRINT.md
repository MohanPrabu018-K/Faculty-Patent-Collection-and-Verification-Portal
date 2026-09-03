# Faculty Patent Collection Portal — Master Project Blueprint

**Version:** 1.0
**Status:** Approved master reference document
**Stack:** Python FastAPI + FastAPI BackgroundTasks + React (TypeScript) + PostgreSQL
**Constraint:** Free-first, no Docker, no mandatory paid APIs, AI-assisted + human-verifiable

> **Architecture update (2026-08):** Document processing no longer uses Celery/Redis.
> The deterministic 11-agent pipeline runs in-process via **FastAPI `BackgroundTasks`**
> (`app.workers.orchestrator_task.run_document_pipeline`, scheduled from
> `POST /api/v1/uploads/`). OCR is performed by the free **OCR.Space** HTTP API
> (`OCRSPACE_*` env vars, HTTP-429 retry/backoff) instead of local Tesseract.
> Redis/Celery are not required to run or process uploads. Mentions of Celery,
> Redis-as-broker, and Tesseract below are retained for historical context only.

> This document is the single source of truth for the entire project. It consolidates
> requirements, architecture, data model, security, performance, and the full phased
> implementation plan with per-phase detail. Companion deep-dive documents live in `plans/`.

---

## Table of Contents

1. [Vision & Principles](#1-vision--principles)
2. [Roles](#2-roles)
3. [IP Terminology](#3-ip-terminology)
4. [End-to-End Workflow](#4-end-to-end-workflow)
5. [Extraction Targets](#5-extraction-targets)
6. [Conflict Matrix](#6-conflict-matrix)
7. [Architecture](#7-architecture)
8. [Technology Stack](#8-technology-stack)
9. [Data Model](#9-data-model)
10. [Security Requirements](#10-security-requirements)
11. [Performance Requirements](#11-performance-requirements)
12. [Audit & Notifications](#12-audit--notifications)
13. [Functional Feature Catalog](#13-functional-feature-catalog)
14. [API Surface](#14-api-surface)
15. [Agentic AI Design](#15-agentic-ai-design)
16. [Testing Strategy](#16-testing-strategy)
17. [Phased Implementation Plan](#17-phased-implementation-plan)
18. [Acceptance Criteria](#18-acceptance-criteria)
19. [Out of Scope / Future](#19-out-of-scope--future)

---

## 1. Vision & Principles

A production-grade, free-first, institutional web portal that collects, verifies,
organizes, and manages **patents and design registrations** associated with faculty.

**Core principle (enforced in every layer):**

> **AI assists. Rules validate. Evidence supports. Humans confirm uncertainty.**
> **The database stores controlled results.**

The portal never blindly trusts AI output. Deterministic backend rules own all critical
state transitions. AI produces values + confidence + evidence + recommendations only.

**Non-negotiables:**
- Never hallucinate final facts; missing values are explicit (`UNKNOWN` / `NOT_FOUND` / `VERIFICATION_REQUIRED`).
- No silent wrong-person assignment; ambiguous identities require human confirmation.
- External source failure is non-fatal; every external capability has a free/manual fallback.
- No paid API is mandatory; all external capabilities sit behind provider interfaces.
- No Docker; native `venv` + local PostgreSQL (no Redis; processing via FastAPI BackgroundTasks).
- Client-side permissions are never trusted; authorization is server-side only.

---

## 2. Roles

| Role | Responsibilities |
|------|------------------|
| **SUPER ADMIN** | Institution-wide management: faculty accounts, departments, designations, activation/deactivation, credential reset, all IP records, verification management, conflict resolution, duplicate management, association management, analytics, audit logs, security events, exports. |
| **FACULTY** | Profile, dashboard, upload certificates, view own IP records + status, pending actions, sent/received association requests, conflict notifications, search/filter own records, review extracted metadata before final submission. |

A future **Verifier / Reviewer** role can be added without schema rework (out of scope initially).

---

## 3. IP Terminology

Three internal document types are distinguished. This is a **hard business rule**:

| Internal Type | Meaning | Key identifiers |
|---------------|---------|-----------------|
| `PATENT` | Utility/design patent | Patent Number, Application Number |
| `DESIGN_REGISTRATION` | Design registration certificate | Design Number, Serial Number |
| `UNKNOWN_OTHER` | Unclassified/other IP document | — |

- A **Design Number belongs to a design-registration context** and is NEVER stored as a Patent Number.
- The `ip_type` enum drives classification, extraction fields, and duplicate-matching key selection.

---

## 4. End-to-End Workflow

```
Faculty Login → Dashboard → Upload Certificate → Secure File Validation
→ Background Processing → QR Detection → OCR → Document Classification
→ Field Extraction → Public/Official Verification (when feasible)
→ Faculty Identity Matching → Duplicate Detection
→ Contributor/Association Analysis → Conflict Detection
→ Faculty Review → Association Requests → Other-Faculty Approval
→ Final Verification → Database → Audit Log → Analytics/Reports
```

### Upload Processing Pipeline (layered)

```
file validation → preprocessing → QR detection → QR decoding → OCR
→ layout understanding → field extraction → confidence scoring
→ cross-validation → human review (when needed)
```

- QR failure → OCR fallback.
- OCR uncertainty → preprocessing/extraction fallback.
- Still uncertain → request verification. **Never crash.**

---

## 5. Extraction Targets

Attempt to extract (each with a confidence score + evidence pointer):

- Faculty/contributor name, designation, department
- Patent Number, Application Number, Design Number, Serial Number
- Published Date, Filing Date, Grant Date
- Patent/Design Title, Patentee, Applicant
- Inventor/contributor names + author/contributor order
- Institution/organization, country
- Certificate type, QR data, verification/source reference

---

## 6. Conflict Matrix

| # | Conflict | Resolution strategy |
|---|----------|---------------------|
| C1 | Duplicate upload of same IP by another faculty | Identifier/fingerprint match → "already uploaded by Faculty A"; offer view / request association / report incorrect / cancel. No second master record. |
| C2 | Same-name faculty in multiple departments | Score name + institution + department + designation + public data + prior associations; low confidence → human confirmation. Never silently attach. |
| C3 | Institution mismatch (internal vs external) | External contributors represented as `EXTERNAL_CONTRIBUTOR` unless verified as institutional faculty. |
| C4 | Missing faculty name on certificate | identifier → public verification → internal search → existing associations → metadata matching → human confirmation if uncertain. Not a system error. |
| C5 | Verification mismatch (AI vs official source) | Flag `VERIFICATION_REQUIRED` / `MISMATCH`; official source evidence wins, pending human review. |
| C6 | AI uncertainty / low confidence | Route to human review queue with evidence + recommendations. |
| C7 | Contributor-order ambiguity | Preserve order as extracted; mark confidence; human confirmable. |
| C8 | Patent vs Design misclassification | Classifier + identifier-shape rules cross-check; mismatch → human review. |

---

## 7. Architecture

### 7.1 High-Level Diagram

```mermaid
flowchart TB
    Browser[React SPA Browser] -->|HTTPS| Nginx[Nginx Reverse Proxy]
    Nginx --> API[FastAPI API Layer]
    Nginx --> Static[Static Assets]
    API --> Postgres[PostgreSQL]
    API --> Storage[Private Storage]
    API --> BG[FastAPI BackgroundTasks]
    BG --> AI[AI Agents Orchestrator - 11 deterministic agents]
    AI --> OCR[OCR.Space free API]
    AI --> QR[QR Service]
    AI --> Verify[Verification Adapters]
    AI --> Storage
    AI --> Postgres
    Verify --> External[Public Official Sources]
```

### 7.2 Component Responsibilities

| Component | Responsibility |
|-----------|----------------|
| **React SPA** | Faculty/admin UI; never trusted for authorization; CSRF tokens on mutations. |
| **FastAPI API** | AuthN/AuthZ, validation, RBAC, business rules, rate limiting, audit emission. |
| **PostgreSQL** | Single source of truth for controlled data; constraints + indexes. |
| **FastAPI BackgroundTasks** | Runs the deterministic 11-agent pipeline in-process after the upload response (no broker/queue). |
| **OCR.Space API** | Free external OCR (base64 image → text); HTTP-429 retry/backoff; missing key degrades gracefully to empty text. |
| **Private Storage** | Uploaded certificates + evidence; authorization-controlled; never web-served directly. |
| **Verification Adapters** | Pluggable, timeout/retry/cache, source tracking, manual fallback. |
| **AI Orchestrator** | Coordinates specialized agents; emits confidence + evidence + recommendations only. |

### 7.3 Module Breakdown

```
backend/app/
  api/            # routers + dependencies
  core/           # config, security, exceptions, logging, audit
  models/         # SQLAlchemy models
  schemas/        # Pydantic schemas
  services/       # business logic (rules, no direct DB writes from AI)
  agents/         # AI agents + orchestrator
  workers/        # BackgroundTasks pipeline runner (orchestrator_task.py)
  verification/   # verification adapters
  storage/        # storage abstraction
  utils/          # identifiers, dates, fingerprints, similarity

frontend/src/
  app/            # routes, layout
  features/       # faculty, admin, upload, search, analytics
  components/     # shared UI
  api/            # typed API client
  hooks/          # queries + mutations
  stores/         # auth/session state
```

---

## 8. Technology Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Language | Python 3.12 | Best free OCR/AI/vision ecosystem |
| Web framework | FastAPI + Pydantic v2 | Typed, async, auto OpenAPI docs |
| ORM/Migrations | SQLAlchemy 2.0 (async) + Alembic | Mature, typed, migration-first |
| DB | PostgreSQL 16 | Trigram indexes, JSONB, ACID |
| Async processing | FastAPI BackgroundTasks | In-process, no broker/queue, no Redis dependency |
| OCR | OCR.Space free API (httpx) | Free tier, HTTP-429 retry/backoff, graceful degradation |
| Image preprocessing | OpenCV (headless) | Free |
| PDF processing | PyMuPDF + pdfplumber | Free |
| QR detection | pyzbar (OpenCV fallback) | Free |
| Optional local LLM | Ollama (Llama 3.x) | Free, self-hosted, rule-based fallback |
| Frontend | React 18 + TypeScript + Vite | Fast, typed, code-splitting |
| Data fetching | TanStack Query | Caching, background refetch |
| Forms/validation | React Hook Form + Zod | Shared validation |
| UI | Tailwind CSS + Radix UI | Accessible, institutional SaaS |
| Charts | Recharts | Free analytics |
| Password hashing | Argon2id | Strong, modern |
| Auth | JWT httpOnly Secure SameSite cookie + CSRF | Secure session model |
| Reverse proxy | Nginx + Let's Encrypt | HTTPS, free TLS |
| Storage | Local private FS (abstraction → MinIO/S3) | Free-first, swappable |
| Malware scan | ClamAV (optional local daemon) | Free |
| Testing | pytest, httpx, Playwright, bandit, safety, locust | Free |
| Monitoring | Prometheus metrics + structured logging + health checks | Free |

> **No Docker.** Native `venv` + local PostgreSQL. Redis is not required (processing runs via FastAPI BackgroundTasks).

### Provider Abstraction Interfaces (Free-First)

| Interface | Free default | Optional/fallback |
|-----------|--------------|-------------------|
| `OcrProvider` | OCR.Space free API | PaddleOCR / Tesseract (not wired) |
| `QrDecoder` | pyzbar | OpenCV QRCodeDetector |
| `LlmProvider` | rule-based heuristics | Ollama (local) |
| `EmbeddingProvider` | `rapidfuzz` trigram | sentence-transformers |
| `VerificationProvider` | official site adapters + manual | configurable per-country |
| `ObjectStorage` | local private FS | MinIO/S3 |
| `MalwareScanner` | none (flag only) | ClamAV |
| `EmailNotifier` | in-app only | SMTP (self-host) |

### 8.1 Python Dependencies (pyproject.toml)

```
[project]
name = "faculty-patent-portal"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
    "pydantic[email]>=2.6",
    "pydantic-settings>=2.2",
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.29",
    "alembic>=1.13",
    "argon2-cffi>=23.1",
    "pyjwt>=2.8",
    "python-multipart>=0.0.9",
    "aiofiles>=23.2",
    "httpx>=0.27",                      # OCR.Space client (replaces pytesseract + celery/redis)
    "opencv-python-headless>=4.9",
    "pyzbar>=0.1.9",
    "pymupdf>=1.24",
    "pdfplumber>=0.11",
    "pillow>=10.3",
    "rapidfuzz>=3.6",
    "numpy>=1.26",
    "httpx>=0.27",
    "structlog>=24.1",
    "prometheus-fastapi-instrumentator>=6.1",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov>=5.0",
    "httpx>=0.27",
    "bandit>=1.7",
    "safety>=3.0",
    "pip-audit>=2.7",
    "mypy>=1.9",
    "ruff>=0.3",
    "pre-commit>=3.7",
]
docs = ["mkdocs-material>=9.5"]
llm = ["ollama>=0.1"]               # optional local LLM
paddle = ["paddleocr>=2.7"]         # optional alternative OCR
embeddings = ["sentence-transformers>=2.6"]  # optional similarity embeddings

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "S"]
ignore = ["S101"]  # allow asserts in tests

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.mypy]
python_version = "3.12"
strict = true
```

### 8.2 Environment Variables (.env.example)

```
# --- Application ---
APP_NAME=Faculty Patent Collection Portal
APP_ENV=development              # development | staging | production
SECRET_KEY=change-me-in-production
DEBUG=false
API_PREFIX=/api
CORS_ORIGINS=http://localhost:5173

# --- Database ---
DATABASE_URL=postgresql+asyncpg://faculty_user:change-me@localhost:5432/faculty_portal

# --- OCR.Space (free OCR API; replaces Tesseract + Celery/Redis processing) ---
OCRSPACE_API_KEY=                       # free key from https://ocr.space/ocrapi
OCRSPACE_API_URL=https://api.ocr.space/parse/image
OCRSPACE_LANGUAGE=eng
OCRSPACE_OCR_ENGINE=2
OCRSPACE_TIMEOUT_SECONDS=30
OCRSPACE_MAX_RETRIES=3                  # retry HTTP 429 / transient failures
OCRSPACE_BACKOFF_SECONDS=2.0           # linear backoff * attempt

# --- Auth / Session ---
JWT_SECRET=change-me-jwt-secret
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_MINUTES=30
JWT_REFRESH_TOKEN_DAYS=7
COOKIE_SECURE=false              # true in production (HTTPS)
COOKIE_SAMESITE=lax

# --- Upload / Storage ---
STORAGE_BACKEND=local            # local | s3
LOCAL_STORAGE_ROOT=./storage
MAX_UPLOAD_BYTES=20971520        # 20 MB
MAX_PDF_PAGES=50
MAX_IMAGE_DIMENSION=10000
ALLOWED_EXTENSIONS=.pdf,.png,.jpg,.jpeg
CLAMAV_HOST=                     # empty = disabled

# --- Verification ---
VERIFICATION_TIMEOUT_SECONDS=10
VERIFICATION_RETRIES=2
VERIFICATION_CACHE_TTL_SECONDS=86400

# --- Optional LLM ---
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3

# --- Rate Limiting ---
RATE_LIMIT_LOGIN_PER_IP=10
RATE_LIMIT_LOGIN_PER_ACCOUNT=5
RATE_LIMIT_UPLOAD_PER_HOUR=50
RATE_LIMIT_SEARCH_PER_MINUTE=30
ACCOUNT_LOCKOUT_ATTEMPTS=5
ACCOUNT_LOCKOUT_SECONDS=900
```

### 8.3 Complete Repository Structure

```
faculty-patent-portal/
├── PROJECT_BLUEPRINT.md        # this master reference
├── README.md
├── .env.example
├── .gitignore
├── scripts/
│   ├── setup_dev.sh            # native venv + service bootstrap (no Docker)
│   ├── run_dev.sh              # uvicorn + vite (no celery worker)
│   └── run_tests.sh
├── backend/
│   ├── app/
│   │   ├── main.py             # FastAPI app factory
│   │   ├── api/
│   │   │   ├── deps.py         # shared dependencies (auth, RBAC, rate limit)
│   │   │   ├── auth.py
│   │   │   ├── faculty.py
│   │   │   ├── admin.py
│   │   │   ├── uploads.py
│   │   │   ├── ip_records.py
│   │   │   ├── associations.py
│   │   │   ├── duplicates.py
│   │   │   ├── conflicts.py
│   │   │   ├── verification.py
│   │   │   ├── search.py
│   │   │   ├── analytics.py
│   │   │   ├── exports.py
│   │   │   ├── notifications.py
│   │   │   └── audit.py
│   │   ├── core/
│   │   │   ├── config.py        # pydantic-settings
│   │   │   ├── security.py      # hashing, JWT, CSRF, headers
│   │   │   ├── exceptions.py
│   │   │   ├── logging.py       # structlog
│   │   │   └── audit.py
│   │   ├── models/
│   │   │   ├── base.py
│   │   │   ├── user.py
│   │   │   ├── institution.py   # department, designation
│   │   │   ├── ip_record.py
│   │   │   ├── association.py
│   │   │   ├── file.py
│   │   │   ├── job.py
│   │   │   ├── verification.py
│   │   │   ├── conflict.py
│   │   │   ├── notification.py
│   │   │   └── audit.py
│   │   ├── schemas/
│   │   ├── services/            # business rules (owns persistence decisions)
│   │   ├── agents/              # AI agents + orchestrator (read/recommend only)
│   │   ├── workers/             # BackgroundTasks pipeline runner
│   │   ├── verification/        # verification adapters
│   │   ├── storage/             # storage abstraction
│   │   └── utils/
│   ├── alembic/
│   ├── tests/
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   ├── features/
│   │   ├── components/
│   │   ├── api/
│   │   ├── hooks/
│   │   └── stores/
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
└── docs/
    ├── architecture.md
    ├── setup.md
    ├── database.md
    ├── api.md
    ├── ai-agents.md
    ├── security.md
    ├── deployment.md
    ├── testing.md
    └── troubleshooting.md
```

### 8.4 Native Setup (No Docker)

**Prerequisites:** Python 3.12, Node.js 20+, PostgreSQL 16, and libzbar (for
`pyzbar`) installed natively. No Redis, no Celery, no Tesseract — OCR is the
free OCR.Space HTTP API (set `OCRSPACE_API_KEY` in `.env`).

```bash
# 1. Backend
cd backend
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 2. Database (one-time)
createdb faculty_portal
alembic upgrade head
alembic seed                          # seed super admin + departments

# 3. Environment
cp ../.env.example .env               # then edit values

# 4. Frontend
cd ../frontend
npm install

# 5. Run (two processes — no Celery worker)
#    Terminal 1: uvicorn app.main:app --reload    # runs the BackgroundTasks pipeline in-process
#    Terminal 2: npm run dev
```

---

## 9. Data Model

### 9.1 Entities

| Entity | Purpose |
|--------|---------|
| `user` | Faculty + admin; role discriminator |
| `department` | Institutional departments |
| `designation` | Faculty designations |
| `ip_record` | Master record; `ip_type` enum, verification/processing status |
| `ip_contributor` | Link user↔record; role, order, internal/external flag |
| `external_contributor` | Non-institutional contributors |
| `ip_file` | Uploaded file metadata, fingerprint, storage key |
| `processing_job` | Async job status, retries, error |
| `verification_attempt` | Source, result, evidence, timestamp |
| `association_request` | Requester, recipient, status, reason, response |
| `duplicate_case` | Duplicate detection results |
| `identity_conflict` | Ambiguous identity matches |
| `conflict_case` | Generic conflict with resolution workflow |
| `notification` | In-app notifications |
| `audit_log` | Actor, action, target, status, before/after JSONB |
| `security_event` | Login failures, lockouts, abuse |
| `rate_limit_state` | Rate-limit counters |
| `export_job` | Export generation jobs |

### 9.2 Key Enums & Statuses

- `ip_type`: `PATENT` | `DESIGN_REGISTRATION` | `UNKNOWN_OTHER`
- `processing_status`: `PENDING` | `QUEUED` | `PROCESSING` | `AWAITING_REVIEW` | `COMPLETED` | `FAILED`
- `verification_status`: `UNVERIFIED` | `VERIFICATION_REQUIRED` | `VERIFIED` | `MISMATCH`
- `association_status`: `PENDING` | `APPROVED` | `REJECTED` | `CLARIFICATION_REQUESTED` | `CANCELLED`
- `conflict_status`: `OPEN` | `RESOLVED` | `DISMISSED`

### 9.3 Indexing Strategy

- Unique/partial indexes on strong identifiers (patent_number, design_number, application_number) within `ip_type`.
- B-tree indexes on filter columns: `faculty_id`, `department_id`, `designation_id`, `ip_type`, `verification_status`, `processing_status`, `created_at`.
- Trigram index on `title` and `faculty_name` for similarity search.
- GIN index on JSONB audit `before/after` and `metadata`.
- Composite indexes for the most common filter combinations (department + ip_type + date range).

---

## 10. Security Requirements

- Argon2id password hashing; JWT in httpOnly Secure SameSite cookies; CSRF double-submit.
- RBAC enforced server-side on every route (never client-only).
- Input validation (Pydantic), output encoding, parameterized queries (SQLAlchemy) — no SQL injection.
- Restrictive CORS, secure HTTP headers (HSTS, CSP, X-Content-Type-Options, etc.).
- Secrets only via environment variables / secret manager; no secrets in source; no prod debug mode.
- Safe error responses (no stack traces leaked).
- Rate limiting + account lockout for: login, password reset, upload, search, APIs, association requests, exports, verification requests (per-IP + per-account).
- File security: extension + MIME + magic-byte validation, size/page/dimension limits, safe generated filenames, private storage, authorized downloads, ClamAV where available, no execution, no user-controlled paths.

### Threat Coverage

| Threat | Mitigation |
|--------|-----------|
| Auth bypass | Server-side session validation on every protected route |
| AuthZ bypass / IDOR | Ownership checks + role checks in services (not just routes) |
| SQL injection | SQLAlchemy parameterized queries only |
| XSS | Output encoding in React + CSP; no `dangerouslySetInnerHTML` |
| CSRF | Double-submit CSRF token for all mutations |
| Brute force | Login throttling + account lockout + per-IP rate limits |
| Malicious upload | Magic-byte + MIME + extension + size + ClamAV + private storage |
| Path traversal | Server-generated filenames only; no user-controlled paths |

---

## 11. Performance Requirements

- Async background processing: upload returns status immediately; OCR/AI/verification never block HTTP.
- Pagination everywhere; lazy loading; code splitting; DB indexes; query optimization (no N+1).
- Connection pooling, compression, optimized assets.
- Optional caching layer for hot reads (dashboards, filters, verification results) — not currently wired.
- Never load thousands of records or huge frontend bundles at once.

---

## 12. Audit & Notifications

### 12.1 Audit Events

Login/logout, failed login, faculty CRUD, uploads, processing, verification, association
request/approval/rejection, admin edits, archive/delete, exports, security events —
each with **actor, action, target, timestamp, status, before/after values** (JSONB where appropriate).

### 12.2 Notifications

In-app notifications for:
- upload completed
- verification completed
- association request
- approval/rejection
- conflict
- admin action required
- processing failure
- correction required

Email optional; no paid API required.

---

## 13. Functional Feature Catalog

### 13.1 Super Admin Features

- **Dashboard**: institution-wide KPIs, recent activity, pending conflicts/verifications.
- **Faculty Management**: create/edit/activate/deactivate/credential reset; search + filter.
- **Institution Management**: departments + designations CRUD.
- **All IP Records**: view/edit/archive all records; override verification.
- **Verification Management**: review verification attempts, resolve mismatches.
- **Conflict Resolution**: queue of identity/duplicate/verification conflicts.
- **Duplicate Management**: merge/keep/dismiss duplicate cases.
- **Association Management**: oversight of pending/approved/rejected associations.
- **Analytics**: faculty-wise, department-wise, year-wise, patent-vs-design, verified-vs-pending, collaborative IP, internal-vs-external, upload trends.
- **Audit Logs + Security Events**: filterable, exportable.
- **Exports**: CSV, Excel-compatible, PDF reports (where practical).

### 13.2 Faculty Features

- **Profile**: view/edit own institutional profile.
- **Dashboard**: own IP records, statuses, pending actions.
- **Upload**: PDF/image upload with immediate processing status.
- **My IP Records**: list + filter + detail view.
- **Processing/Verification Status**: per-record tracking.
- **Pending Actions**: review extracted metadata, respond to association requests, resolve conflicts.
- **Association Requests**: sent/received; approve/reject/request clarification.
- **Conflict Notifications**: identity/duplicate/verification alerts.
- **Own Search/Filter**.

### 13.3 Super Admin Combinable Filters

- faculty, faculty ID, department, designation, IP type, patent/design, date range, year/month, verification status, upload/processing status, association status, contributor count, institution, uploader.

### 13.4 Search Fields

- patent number, design number, application number, title, faculty name/ID, institution.

---

## 14. API Surface

| Area | Endpoints (REST) |
|------|------------------|
| Auth | `POST /auth/login`, `POST /auth/logout`, `POST /auth/refresh`, `GET /auth/me`, `POST /auth/csrf` |
| Faculty (admin) | `GET/POST /admin/faculty`, `GET/PATCH/DELETE /admin/faculty/{id}`, `POST /admin/faculty/{id}/reset-credentials`, `POST /admin/faculty/{id}/activate`, `POST /admin/faculty/{id}/deactivate` |
| Departments/Designations | `GET/POST/PATCH/DELETE /admin/departments`, `.../designations` |
| Upload | `POST /uploads` (multipart), `GET /uploads/{id}/status` |
| IP Records | `GET /ip-records`, `GET /ip-records/{id}`, `PATCH /ip-records/{id}` (admin), `GET /ip-records/{id}/file` (authorized download) |
| Associations | `GET/POST /associations`, `POST /associations/{id}/respond` |
| Duplicates | `GET /duplicates`, `POST /duplicates/{id}/resolve` |
| Conflicts | `GET /conflicts`, `POST /conflicts/{id}/resolve` |
| Verification | `GET /verifications`, `POST /ip-records/{id}/verify` |
| Search/Filters | `GET /search` (combinable query params) |
| Analytics | `GET /analytics/overview`, `GET /analytics/by-faculty`, `.../by-department`, `.../by-year`, `.../trends` |
| Exports | `POST /exports`, `GET /exports/{id}/download` |
| Notifications | `GET /notifications`, `POST /notifications/{id}/read` |
| Audit | `GET /audit-logs`, `GET /security-events` |
| Health | `GET /healthz`, `GET /readyz`, `GET /metrics` |

> All mutation endpoints require a valid session + CSRF token + role authorization.
> Full OpenAPI spec auto-generated by FastAPI.

---

## 15. Agentic AI Design

### 15.1 Specialized Agents

| # | Agent | Output |
|---|-------|--------|
| 1 | Document Classification Agent | `ip_type` + confidence |
| 2 | QR Analysis Agent | decoded QR payload + confidence |
| 3 | OCR/Extraction Agent | raw text + layout regions |
| 4 | Document Understanding Agent | structured fields + confidence |
| 5 | Verification Agent | verification recommendation + evidence |
| 6 | Faculty Identity Resolution Agent | candidate matches + confidence |
| 7 | Duplicate Detection Agent | duplicate candidates + evidence |
| 8 | Conflict Resolution Agent | conflict classification + recommendation |
| 9 | Association Recommendation Agent | suggested associations + rationale |
| 10 | Data Quality Agent | completeness/consistency scoring |
| 11 | Report/Analytics Agent | aggregation recommendations (if useful) |

### 15.2 Orchestrator Rules

- Agents are **read/recommend only** — no DB-write authority.
- Each agent returns: `values`, `confidence`, `evidence`, `recommendation`, `detected_conflicts`, `verification_status`.
- Backend business rules decide persistence.
- Critical identity/association changes require human confirmation.
- Every agent run is logged to the AI audit trail.

### 15.3 Confidence & Fallback

- Rule-based heuristics always available as the zero-dependency baseline.
- Optional local LLM (Ollama) enhances extraction when available; absence never breaks the pipeline.
- Low confidence routes to human review.

---

## 16. Testing Strategy

| Layer | Tools | Coverage |
|-------|-------|----------|
| Unit | pytest | utils, services, normalization, validation rules |
| API | httpx + ASGITransport | auth, RBAC, CRUD, upload, association, filters |
| Integration | pytest + test DB | DB constraints, migrations, workflows |
| E2E | Playwright | login, upload, review, association, admin flows |
| Security | bandit + safety + custom tests | injection, XSS, CSRF, IDOR, brute force, rate limits, malicious uploads |
| AI evaluation | fixture corpus | classification/extraction accuracy, no hallucination |
| Performance | locust | login, search, filters, upload under load |

### Test Scenarios (mandatory)

- authentication bypass, authorization bypass, IDOR
- injection (SQL/XSS), CSRF
- brute force, rate limits
- malicious uploads
- ambiguous identities, duplicate uploads
- association workflows
- multiple certificate formats

---

## 17. Phased Implementation Plan

The original 26 phases are **reordered, merged, and split** into **A–W** to minimize rework.

| Phase | Scope | Deliverables | Gate |
|-------|-------|--------------|------|
| **A** | Requirements + Architecture | This blueprint + dependency plan | No major requirement undefined |
| **B** | Foundation | Repo structure, `venv`, env config, lint/format, test scaffold, README, native setup scripts | Clean local startup |
| **C** | Database | ERD, schema, Alembic migrations, constraints, indexes, seeds, audit model | Schema supports all workflows |
| **D** | Security core + Auth + RBAC | Argon2, sessions, CSRF, RBAC, login throttling | Unauthorized access impossible |
| **E** | Faculty + institution mgmt | Faculty CRUD, departments, designations, activation, credentials | Admin fully manages accounts |
| **F** | Secure upload | Validation, private storage, fingerprinting, limits | Unsafe files rejected |
| **G** | Background jobs | FastAPI BackgroundTasks, in-process pipeline, ProcessingJob status rows | Long work never blocks the upload response |
| **H** | Faculty workflow shell | Dashboard, profile, upload UI, status, pending actions | Faculty workflow works |
| **I** | QR + OCR + Classification | QR, OCR, preprocessing, classification, confidence | Multiple formats + graceful fallback |
| **J** | Structured extraction | Normalize identifiers/dates, contributors, evidence | No hallucinated verified data |
| **K** | Verification adapters | Adapters, source tracking, timeout/retry/cache, manual fallback | External failure non-fatal |
| **L** | Identity resolution | Name/institution matching, confidence, ambiguity review | No silent wrong-person |
| **M** | Duplicate detection | Identifier matching, fingerprint, similarity, workflow | Duplicate masters prevented |
| **N** | Association requests | Request, notification, approve/reject, history, audit, external representation | Multi-faculty complete |
| **O** | Conflict resolution | Missing names, same-name, mismatch, duplicate, verification, uncertainty | Every conflict defined |
| **P** | Super Admin dashboard | Overview, activity, controls, conflict/verification queues | Central operation |
| **Q** | Search/filters/analytics/exports | Global search, combined filters, charts, CSV/Excel/PDF | Quick institutional retrieval |
| **R** | Notifications + audit | In-app notifications, audit history, security events | Critical actions traceable |
| **S** | Security hardening | Rate limits, headers, CORS, CSRF, upload hardening, secrets, safe errors | Security review passed |
| **T** | Performance optimization | Caching, pagination, lazy loading, background jobs, assets | No slow workflows |
| **U** | Agentic AI orchestration | Orchestrator, agent boundaries, confidence/evidence, human-in-loop, AI audit | AI within permissions |
| **V** | Comprehensive testing | Unit, API, integration, E2E, security, AI, performance | Critical workflows automated |
| **W** | Production + release | Production config, HTTPS, backup/recovery, monitoring, docs, final audit | Production-ready |

### Per-Phase Execution Protocol

For each phase:
1. Inspect current repository/project state.
2. Read existing code before modifying it.
3. Identify already completed work.
4. Avoid unnecessary rewrites.
5. Implement current phase.
6. Run relevant tests.
7. Fix regressions.
8. Update documentation.
9. Verify previous phases still work.
10. Produce a concise phase completion report.
11. Automatically continue to the next phase unless a genuine blocker requires human input.

**Human input only for:** institutional policy ambiguity, legal/policy decisions, irreversible destructive actions, missing credentials, or an external dependency with no safe fallback.

---

## 18. Acceptance Criteria

The portal is complete only when:

- [ ] Super Admin manages faculty.
- [ ] Faculty securely logs in.
- [ ] Faculty uploads certificates.
- [ ] Uploads are securely validated.
- [ ] Processing is asynchronous.
- [ ] QR/OCR works where available.
- [ ] Multiple formats are supported.
- [ ] Patent and Design are correctly distinguished.
- [ ] Missing fields do not crash the system.
- [ ] AI does not hallucinate final facts.
- [ ] Verification is supported with fallback.
- [ ] Duplicate IPs are detected.
- [ ] Same-name conflicts are handled.
- [ ] External contributors are supported.
- [ ] Association requests work.
- [ ] Faculty can approve/reject.
- [ ] Admin can resolve conflicts.
- [ ] Combined filters work.
- [ ] Analytics and exports work.
- [ ] Notifications work.
- [ ] Audit logs work.
- [ ] Rate limiting works.
- [ ] File security works.
- [ ] Server-side authorization works.
- [ ] Secrets are protected.
- [ ] HTTPS is enabled in production.
- [ ] Performance is optimized.
- [x] Background processing runs the 11-agent pipeline via FastAPI BackgroundTasks.
- [ ] Critical workflows have automated tests.
- [ ] Backup/recovery is documented.
- [ ] No critical/high security issue remains unresolved.

---

## 19. Out of Scope / Future

- Dedicated **Verifier / Reviewer** role (schema-ready, not initially built).
- Multi-institution federation / tenant model (single institution initially).
- Paid/hosted AI or search integrations (optional adapters only, never mandatory).
- OCR language packs beyond those bundled free.
- Blockchain/notarization of verification evidence.

---

## Final Principle

**AI assists. Rules validate. Evidence supports. Humans confirm uncertainty. The database stores controlled results.**

Build the portal as:
**Fast + Secure + Reliable + Auditable + Free-first + AI-assisted + Human-verifiable + Production-grade.**
