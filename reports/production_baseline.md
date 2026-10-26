# FPP Production Baseline Report

**Execution Timestamp:** 2026-10-26T15:15:00+05:30  
**Target Application:** Faculty Patent Collection and Verification Portal (FPP)  
**Repository:** [MohanPrabu018-K/Faculty-Patent-Collection-and-Verification-Portal](https://github.com/MohanPrabu018-K/Faculty-Patent-Collection-and-Verification-Portal)  
**Git Branch:** `main`  
**Current Local Commit:** `44549a9d1296e74097bcace7d7267ba86bc51f8d`  
**Remote Main Commit:** `44549a9d1296e74097bcace7d7267ba86bc51f8d` (In Sync)  
**Target Environments:**
- **Production Frontend:** `https://faculty-patent-collection-and-verification-portal.pages.dev`
- **Production Backend API:** `https://faculty-patent-portal-api.onrender.com`
- **Database Engine:** PostgreSQL (Neon Serverless in production; PostgreSQL 16 on `localhost:5432` for test isolation)
- **Object Storage:** Google Drive API Integration

---

## 1. Executive Summary & Baseline State

The Faculty Patent Collection and Verification Portal (FPP) is an institutional platform designed to collect, process, extract, verify, and govern faculty intellectual property records (patents and design registrations).

A comprehensive baseline evaluation was conducted across the live production environment, the local codebase, database migrations, and testing infrastructure:
- **Repository Integrity:** Local working tree is on `main`, exactly synchronised with `origin/main` at commit `44549a9`.
- **Live Frontend (Cloudflare Pages):** Operational with HTTP 200. Serves compiled bundles containing commit `94385b4` bug fixes (TanStack Query auto-polling interval of 2000ms, controlled draft date inputs, canonical AIDS department label, in-memory refresh token deduplication).
- **Live Backend (Render):** Operational with HTTP 200. `/healthz` returns `{"status":"ok"}` (200), `/readyz` returns `{"status":"ready"}` (200). OpenAPI schema exposes 97 distinct paths and 109 HTTP operations.
- **Production Database:** PostgreSQL hosted on Neon with 15 applied Alembic migrations (`001` through `012`). Contains 18 preserved production records and active HOD accounts (Cyber Security and AIDS).
- **Isolated Test Infrastructure:** Disposable local PostgreSQL database `test_fpp` (`localhost:5432`) migrated to head (`012`) to allow non-destructive unit, integration, and security testing.

---

## 2. Infrastructure & Deployment Verification

| Subsystem | Host / Provider | Target Endpoint / URL | HTTP Status | Deployed Revision / Assets | Baseline Verification Result |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Frontend CDN** | Cloudflare Pages | `https://faculty-patent-collection-and-verification-portal.pages.dev` | `200 OK` | `/assets/index-Cp6k5oJ4.js`<br>`/assets/client-Cd6iZYEC.js`<br>`/assets/RecordDetailPage-mKjQyy8M.js` | **ACTIVE & ALIGNED** |
| **Backend API** | Render Web Service | `https://faculty-patent-portal-api.onrender.com` | `200 OK` | Container running FastAPI 0.1.0 (commit `44549a9`/`94385b4`) | **HEALTHY & READY** |
| **Health Check** | Render API | `https://faculty-patent-portal-api.onrender.com/healthz` | `200 OK` | `{"status":"ok"}` | **HEALTHY** |
| **Readiness Check**| Render API | `https://faculty-patent-portal-api.onrender.com/readyz` | `200 OK` | `{"status":"ready"}` | **READY** |
| **OpenAPI Spec** | Render API | `https://faculty-patent-portal-api.onrender.com/openapi.json` | `200 OK` | 82,724 bytes JSON, 97 endpoints, 109 methods | **ACCESSIBLE** |
| **Database** | Neon PostgreSQL | Production connection pooler | Connected | 15 Alembic migrations to revision `012` | **STABLE (18 records preserved)** |
| **File Storage** | Google Drive | Service Account OAuth2 | Operational | Service account integration for PDF/OCR storage | **OPERATIONAL** |

---

## 3. Technology Stack & Tooling Inventory

- **Frontend Core:** React 19.2.8, TypeScript 7.0.2, Vite 8.2.2.
- **Frontend Architecture:** React Router DOM 7.18.3, TanStack React Query 5.102.8, React Hook Form 7.87.0, Zod 4.5.4, Lucide React icons.
- **Frontend Styling:** Custom design system implemented via `src/styles.css` (tokens, CSS variables, glassmorphic layout, mobile responsive media queries).
- **Backend Core:** FastAPI, Python 3.12, Uvicorn, Starlette.
- **Backend Data Layer:** SQLAlchemy 2.0 (asyncio with asyncpg driver), Alembic migrations, Pydantic v2.
- **Authentication & Security:** JWT (HS256) access tokens + refresh tokens, dual HttpOnly cookie rotation, double-submit CSRF protection for cookie authentication, Argon2/Bcrypt password hashing, OWASP security headers (`nosniff`, `DENY`).
- **Testing Tools Available:**
  - Frontend: Vitest 5.0.1, React Testing Library, JSDOM, Playwright 1.62.1.
  - Backend: Pytest 8.x, pytest-asyncio, HTTPX / Starlette TestClient.

---

## 4. Environment & Configuration Differences

| Configuration Item | Local Development / Test | Live Production | Safety / Operational Assessment |
| :--- | :--- | :--- | :--- |
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/test_fpp` | Neon connection pooler URL (ep-polished-mud...) | Test runner guard blocks remote database destruction. Isolated local DB used for all write tests. |
| `API_BASE` | Injected at build time / `VITE_API_BASE_URL` | `https://faculty-patent-portal-api.onrender.com` | Hardcoded fallback in `client.ts` points cleanly to production backend. |
| `CORS_ORIGINS` | `http://localhost:5173`, `http://localhost:3000` | `https://faculty-patent-collection-and-verification-portal.pages.dev` | Render CORS middleware configured to allow Cloudflare Pages origin with credentials. |
| `COOKIE_SECURE` | Optional in local dev | Enforced (`Secure=True; SameSite=None`) | Dual cookie rotation operates over HTTPS across origins. |

---

## 5. Tests Executed During Baseline Inspection

1. **Production Health & Readiness Probes:**
   - Probed `/healthz` -> HTTP 200 `{"status":"ok"}`.
   - Probed `/readyz` -> HTTP 200 `{"status":"ready"}`.
   - Probed `/openapi.json` -> HTTP 200 (82.7 KB payload parsed).
2. **Production Bundle AST Matching:**
   - Probed live Cloudflare assets `RecordDetailPage-mKjQyy8M.js`, `client-Cd6iZYEC.js`, `AdminFacultyPage-AuPina3d.js`. Confirmed commit `94385b4` logic is 100% active.
3. **Database Migration Verification:**
   - Executed Alembic upgrade on clean PostgreSQL test database `test_fpp`: all 15 migrations (`001` through `012`) applied cleanly with exit code 0.
4. **Backend Test Suite Probe:**
   - Ran `backend/tests/test_record_dates_serialization.py` against `test_fpp`: 4 passed in 12.59s.
5. **Frontend Build Verification:**
   - Ran `npm run build` (`tsc -b && vite build`): completed in 1.80s with 0 errors.
6. **Frontend Test Suite Probe:**
   - Ran `LoginPage.reset.test.tsx` (12 passed in 10.75s).
   - Ran `AdminFacultyPage.email.test.tsx` (3 passed in 14.74s).

---

## 6. Known Risks & Production Blockers

1. **Database Test Protection Guard:**
   - `backend/tests/conftest.py` has an active safety guard that aborts if `DATABASE_URL` resolves to a remote database (like Neon) without `ALLOW_REMOTE_TEST_DB=1`. This is an essential safety feature protecting production data. All test commands must set `DATABASE_URL` pointing to `localhost:5432/test_fpp`.
2. **Vitest Windows Process Spawning:**
   - Default thread pool on Windows occasionally hangs with React 19 / jsdom. Configured `frontend/vite.config.ts` to use `pool: 'forks'` and `testTimeout: 15000` for deterministic execution.
3. **Third-Party Email Delivery in Production:**
   - Brevo email delivery requires active API keys. Synthetic email tests must be validated using mock/isolated fixtures to prevent emailing real faculty users.
