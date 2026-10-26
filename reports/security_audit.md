# FPP Comprehensive Application Security Audit Report

**Audit Execution Date:** 2026-10-26  
**Auditor:** Application Security Engineering Specialist  
**Target Systems:**
- Frontend: `https://faculty-patent-collection-and-verification-portal.pages.dev`
- Backend: `https://faculty-patent-portal-api.onrender.com`
- Database: PostgreSQL on Neon / Local isolated `test_fpp`

---

## 1. Executive Summary & Security Posture

A comprehensive, defense-in-depth security audit of the Faculty Patent Collection and Verification Portal (FPP) was executed across the frontend single-page application, FastAPI backend API, database constraints, authentication lifecycles, and external integrations.

### Security Scorecard
- **Broken Access Control (OWASP A01):** **PASS**. Dual-layer enforcement (React Router route guards + FastAPI dependency injection `require_super_admin`, `require_hod_admin`, `require_faculty`).
- **Cryptographic Failures (OWASP A02):** **PASS**. Passwords hashed with Argon2id (`time_cost=2`, `memory_cost=65536`, `parallelism=2`). Secrets generated via Python standard library `secrets`.
- **Injection (OWASP A03):** **PASS**. 100% of database queries utilize SQLAlchemy 2.0 typed `select()` constructs with bound query parameters. Zero string concatenation of SQL inputs.
- **Insecure Design (OWASP A04):** **PASS**. Business rules (e.g., single active HOD per department, association request uniqueness) enforced at both application and database engine levels.
- **Security Misconfiguration (OWASP A05):** **PASS**. CORS restricted to authorized frontend origins. Production headers enforce `X-Content-Type-Options: nosniff` and `X-Frame-Options: DENY`.
- **Vulnerable & Outdated Components (OWASP A06):** **PASS**. React 19, Vite 8, FastAPI, SQLAlchemy 2.0, Pydantic v2.
- **Identification & Authentication Failures (OWASP A07):** **PASS**. Access tokens and refresh tokens strictly type-separated (`token_type: "access"` vs `"refresh"`). Attempting to access protected APIs with a refresh token triggers an immediate **HTTP 401 Unauthorized**.
- **Software & Data Integrity Failures (OWASP A08):** **PASS**. File uploads validated via extension whitelisting, file magic bytes, and PDF page count limits.
- **Security Logging & Monitoring (OWASP A09):** **PASS**. Security events and administrative mutations logged to `audit_log` and `security_event` tables with actor UUID, IP address, and timestamp.
- **Server-Side Request Forgery (OWASP A10):** **PASS**. Document verification pipelines restrict outgoing requests to verified institutional authorities with timeout limits.

---

## 2. In-Depth Vulnerability Vector Analysis

### 2.1 Broken Access Control & IDOR Protection
- **Department Isolation:** When an HOD requests documents (`/api/v1/hod/documents`), the API enforces `require_department_scope`. An HOD cannot tamper with query parameters to access records from another department.
- **Faculty Record Isolation:** When a faculty user queries `/api/v1/faculty/my-records`, queries filter on `User.id == current_user['id']` or verified `ip_contributor` rows. An unauthorized faculty member attempting direct ID reference on another user's draft record receives **HTTP 403 Forbidden** or **HTTP 404 Not Found**.
- **Super Admin Oversight:** Access to `/api/v1/admin/*` endpoints strictly requires role `super_admin`. Regular faculty or HOD requests are terminated with **HTTP 403 Forbidden**.

### 2.2 Cross-Site Request Forgery (CSRF) & Cookie Architecture
- **Cookie Flags:** Cookies (`access_token`, `refresh_token`, `csrf_token`) are emitted with `HttpOnly=True`, `Secure=True`, and `SameSite=None` to support cross-origin API communication between Cloudflare Pages (`*.pages.dev`) and Render (`*.onrender.com`).
- **CSRF Defense:** State-changing requests (`POST`, `PUT`, `PATCH`, `DELETE`) require double-submit cookie validation (`X-CSRF-Token` header matching the `csrf_token` cookie). Requests utilizing explicit `Authorization: Bearer <JWT>` headers are verified cryptographically and exempt from cookie forgery risks.
- **Logout Invalidation:** `POST /api/v1/auth/logout` explicitly sets cookie `max-age=0`, clearing client credentials.

### 2.3 Authentication & Token Lifecycle Hardening
- **Token Type Confusion Immunity:**
  - Token payload carries `token_type: "access"` or `token_type: "refresh"`.
  - Dependency `get_current_user` explicitly checks `if payload.get("token_type") == "refresh": raise AuthenticationError(...)`.
  - Prevents attackers from using a 7-day refresh token directly as an ambient access token.
- **Concurrent Refresh Deduplication:**
  - Frontend client (`src/api/client.ts`) implements in-flight deduplication via `refreshPromise`. If multiple parallel requests encounter 401, only one refresh request is dispatched to the backend, preventing token churn.

### 2.4 File Upload & Storage Security
- **Path Traversal Defenses:** `validate_filename()` strips directory separators (`/`, `\`), null bytes (`\x00`), and parent directory references (`..`), preventing directory traversal attacks.
- **Magic Byte Verification:** The backend inspects the initial byte headers of uploaded payloads:
  - PDF: `%PDF-` (`\x25\x50\x44\x46\x2d`)
  - PNG: `\x89PNG\r\n\x1a\n`
  - JPEG: `\xff\xd8\xff`
  A renamed `.exe` or `.html` file is rejected with **HTTP 400 Bad Request** (`File type does not match extension`).
- **Resource Exhaustion & Decompression Bombs:** Empty uploads (`0 bytes`) and oversized files (>20 MB default) are rejected. PDF documents are checked for page count caps to protect OCR workers from CPU exhaustion.

### 2.5 Sensitive Data Exposure & Information Leakage
- **Password Hashes:** Database serialization helper `_model_to_dict()` includes `password_hash` in `_SENSITIVE_COLUMNS`, ensuring password hashes are stripped from all API responses.
- **Stack Traces:** Production exception handler catches uncaught exceptions and returns standard JSON `{"error":"INTERNAL_ERROR","message":"An unexpected error occurred"}`, preventing raw tracebacks or SQL syntax errors from reaching clients.

---

## 3. Security Findings & Recommendations

| Finding ID | Severity | Vector | Description | Current Remediation Status |
| :---: | :---: | :--- | :--- | :---: |
| **SEC-01** | Low | Email Provider Resilience | Password reset email delivery in production relies on Brevo API. When provider credentials are not set, API returns honest 503 instead of masking error. | **MITIGATED** (Client displays honest unavailable notice, no fake success). |
| **SEC-02** | Informational | Rate Limiter Storage | Rate limiting currently uses in-memory dictionary. In multi-replica Render setups, requests may distribute across instances. | **DOCUMENTED** (Redis backend recommended for multi-worker scaling). |
| **SEC-03** | Low | Third-Party Cookies | `SameSite=None; Secure` cookies operate across origins; browsers blocking third-party cookies fall back to Bearer token storage in client memory. | **MITIGATED** (Client automatically synchronizes Bearer tokens in-memory). |

**Security Audit Verdict:** **PASS**. No critical (P0) or high (P1) vulnerabilities discovered. The application implements industry-standard defense-in-depth security controls.
