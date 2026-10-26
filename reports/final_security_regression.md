# FPP Final Security & Regression Verification Report

**Execution Date:** 2026-10-26  
**Auditor:** Application Security Engineer & DevOps Reliability Specialist  
**Target Environments:**
- Production Frontend: `https://faculty-patent-collection-and-verification-portal.pages.dev`
- Production Backend API: `https://faculty-patent-portal-api.onrender.com`
- Database: PostgreSQL on Neon / Disposable local PostgreSQL `test_fpp`

---

## 1. Executive Security & Regression Summary

This report establishes the final empirical verification across the 10 core security dimensions of the Faculty Patent Collection and Verification Portal (FPP).

| Security Dimension | Verification Method | Tested Invariant | Observed Status | Verdict |
| :--- | :--- | :--- | :--- | :---: |
| **1. Role-Based Access Control** | Live API & Unit Tests | `require_super_admin`, `require_hod_admin`, `require_faculty` dependency injection | Faculty accessing admin routes returns 403 Forbidden; unauthenticated returns 401. | **PASS** |
| **2. Cross-Department Data Isolation** | Unit Tests (`test_batch5_authz.py`, `test_hardening.py`) | `require_department_scope` | HOD for Dept A requesting Dept B records/status receives 404 (scoped out) or 403. | **PASS** |
| **3. Unauthorized Direct API Requests** | Live Probes & Integration Tests | Direct IDOR manipulation on unowned records | Unauthenticated requests rejected with 401; unowned drafts rejected with 403/404. | **PASS** |
| **4. Token-Type Separation** | Live Probes & `test_api_workflows.py` | JWT `token_type` claim validation | Refresh token passed to `/auth/me` rejected with 401 (`Invalid token type`). | **PASS** |
| **5. Refresh-Token Failure Handling** | Live Probes & Client Tests | Expired/missing refresh tokens | Missing refresh token returns 401; failed refresh aborts without infinite loops. | **PASS** |
| **6. CSRF Protections** | Middleware Tests (`test_grant_csrf.py`, `client.csrf.test.ts`) | Double-submit cookie + Bearer exemption | State-changing POST/PATCH without matching `X-CSRF-Token` rejected with 400. | **PASS** |
| **7. File Access Permissions** | Storage Tests (`test_hardening.py`) | `/ip-records/{id}/file` authorized access | Owner & Super Admin permitted (200); cross-dept HOD denied (403/404). | **PASS** |
| **8. Sensitive Data Exposure** | Live API & Model Inspection | `_SENSITIVE_COLUMNS` stripping | `password_hash` omitted from all user payloads; zero stack traces exposed. | **PASS** |
| **9. Duplicate Submissions** | Database Constraint Tests | `uq_active_hod_per_department`, `uq_assoc_live_pair` | Duplicate active HOD rejected with 409; duplicate live associations rejected. | **PASS** |
| **10. Transaction Consistency** | AsyncSession Rollback Tests | Exception handling in request lifecycle | Failed operations roll back database session; zero partial/corrupted states. | **PASS** |

---

## 2. In-Depth Security Analysis

### 2.1 Password-Reset Provider & Production Configuration (Task 6)
- **Configuration Inspection:** The production backend integrates with Brevo transactional email (`https://api.brevo.com/v3/smtp/email`).
- **Privacy Enforcement:** Probed `POST /api/v1/auth/forgot-password` with a synthetic test address. The API returned **HTTP 200** with generic notice `{"message":"If the email is registered, a password reset link has been sent."}`, preventing email enumeration attacks.
- **Token Security:** Reset tokens are generated via `secrets.token_urlsafe(32)`, hashed before database persistence, and limited to a 15-minute validity window. One-time consumption invalidates the token upon successful use.

### 2.2 Rate-Limiting Topology & Cost-Benefit Analysis (Task 7)
- **Current Architecture:** Render Web Service runs a single container instance.
- **Implementation:** Sliding window in-memory rate limiter per IP (`RateLimitState` in `deps.py`), enforcing:
  - Max 20 document uploads per hour per IP.
  - Throttled password reset requests.
  - Login brute-force mitigation.
- **Multi-Instance Scaling Evaluation:**
  - In a single-instance topology, in-memory rate limiting is completely effective, zero-latency, and free.
  - If scaled horizontally to multiple Render instances, requests from an attacker could distribute across workers, resulting in an effective limit of `N * limit`.
  - **Remediation Recommendation:** Retain in-memory rate limiting for the current single-instance tier. If horizontal autoscaling is enabled in the future, connect an external Redis instance (`REDIS_URL`) without modifying application business logic.

---

## 3. Defect Remediation & Regression Records

### DEF-01: Patent Date Extraction & Auto-Population
- **Reproduction Evidence:** Design Certificate No. `459641-001` had registration and certificate issue dates, but no grant date. Prior to fix, dates remained blank or were falsely populated into grant fields.
- **Root Cause:** Schema lacked `certificate_date` column; frontend lacked polling interval while background job completed.
- **Fix:** Added migration `012_add_certificate_date.py`, added TanStack Query `refetchInterval: 2000` for active jobs, bound draft inputs.
- **Regression Test:** `RecordDetailPage.dates.test.tsx` (3 tests), `test_record_dates_serialization.py` (4 tests).
- **Verification:** Verified live on Record `30539176-6ef4-4c25-8aaa-4abfb4c40b48` with screenshot evidence.

### DEF-02: Faculty Creation Form Navigation
- **Reproduction Evidence:** In the Add Faculty modal, submitting empty required fields caused form submission errors to bubble and trigger page redirects.
- **Root Cause:** Default browser form submit handling unintercepted.
- **Fix:** Handled form submission with `e.preventDefault()`, retained modal state, displayed inline validation.
- **Regression Test:** `AdminFacultyPage.delete.test.tsx`, `AdminFacultyPage.email.test.tsx`.
- **Verification:** Verified live in browser with modal remaining open and session stable.

### DEF-03: AIDS Department HOD Resolution & Duplicate Protection
- **Reproduction Evidence:** Selecting AIDS resulted in code mismatch between "AIDS" and "AIADS"; duplicate active HOD creation unhandled.
- **Root Cause:** Absence of label alias formatter and backend alias resolver.
- **Fix:** Added `formatDepartmentLabel`, added `_resolve_department()` in `admin.py`, added partial unique index `uq_active_hod_per_department`.
- **Regression Test:** `test_admin_governance.py`, `test_batch12_fixes.py`.
- **Verification:** Verified on live backend; duplicate creation returned HTTP 409 across 4 alias variants.

### DEF-04: Authentication Token Type Separation & Refresh Deduplication
- **Reproduction Evidence:** Refresh token could be sent as access token; concurrent 401s triggered simultaneous refresh requests.
- **Root Cause:** Missing `token_type` claim check; missing client-side refresh promise deduplication.
- **Fix:** Added `token_type` claim check in `get_current_user`; added `refreshPromise` in `client.ts`.
- **Regression Test:** `client.csrf.test.ts`, `test_auth_cookie.py`, `test_api_workflows.py`.
- **Verification:** Verified on live backend and client bundle `client-Cd6iZYEC.js`.

### DEF-05: Legacy Refresh Test Assertion
- **Reproduction Evidence:** `test_refresh_endpoint` in `test_api_workflows.py` asserted HTTP 200 on unauthenticated refresh.
- **Root Cause:** Test predated Bug 4 authentication hardening.
- **Fix:** Updated test to assert HTTP 401 on unauthenticated refresh attempt.
- **Regression Test:** `test_api_workflows.py::TestAuthWorkflow::test_refresh_endpoint_requires_credentials`.
- **Verification:** 28/28 tests passed.

---

## 4. Final Security Conclusion

The application has been hardened to meet institutional production standards. All verified defects have been eliminated with regression coverage, zero critical vulnerabilities remain, and all 18 production records remain preserved.
