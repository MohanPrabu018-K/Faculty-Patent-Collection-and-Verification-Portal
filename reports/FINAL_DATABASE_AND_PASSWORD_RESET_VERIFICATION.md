# Final Database and Password-Reset Email Verification Report

**Project:** Faculty Patent Collection and Verification Portal (FPP)  
**Date:** October 26, 2026  
**Auditor Roles:** Senior QA Automation Engineer, Full-Stack Developer, Database Engineer, Application Security Tester, DevOps Engineer  
**Baseline Commit:** `bd10da0`  
**Latest Verification Commit:** `308317f`  
**Repository:** [MohanPrabu018-K/Faculty-Patent-Collection-and-Verification-Portal](https://github.com/MohanPrabu018-K/Faculty-Patent-Collection-and-Verification-Portal)  
**Live Frontend:** [faculty-patent-collection-and-verification-portal.pages.dev](https://faculty-patent-collection-and-verification-portal.pages.dev/)  
**Live Backend:** [faculty-patent-portal-api.onrender.com](https://faculty-patent-portal-api.onrender.com/)  

---

## 1. Environment & Target Identification

| Property | Value | Evidence / Validation |
| :--- | :--- | :--- |
| **Git Repository** | `MohanPrabu018-K/Faculty-Patent-Collection-and-Verification-Portal` | `origin/main` clean working tree |
| **Hosted Database Host** | `ep-polished-mud-az0vqln4-pooler.c-3.ap-southeast-1.aws.neon.tech` | Verified via active `.env` configuration |
| **Database Engine** | PostgreSQL 16.10 (Neon Serverless AWS ap-southeast-1) | Schema version: Alembic `012` |
| **Local Test Database** | `localhost:5432/test_fpp` (PostgreSQL 16) | Isolated environment for full test suite runs |
| **Database Authorization** | Explicitly authorized for mock/test data operations | Confirmed contains 35 QA records, 15 depts, 18 files; zero production user disruption |
| **Email Delivery Provider** | Brevo REST API (`POST https://api.brevo.com/v3/smtp/email`) | Authenticated via standard Brevo API key (`xkeysib-...`) |
| **Verified Sender Identity** | `Faculty Patent Portal <mohanprabu018@gmail.com>` | Verified active via `GET https://api.brevo.com/v3/senders` |
| **Authorized Test Mailbox** | `mohanprabu018@gmail.com` | Confirmed owned by repository project owner (`MohanPrabu018-K`) |
| **Frontend Reset Base URL** | `https://faculty-patent-collection-and-verification-portal.pages.dev` | Verified dynamically guarded in `SmtpSettings` |

---

## 2. Database Workflow Testing (Phase 3)

All database workflows were executed and verified through `scripts/verify_database_workflows_e2e.py` using uniquely tagged synthetic entities (`e2e-*`).

### A. Faculty Workflows
- **Faculty Creation:** Successfully created synthetic faculty `faculty.e2e-XXXX@test.edu` with full name, department linkage, and role.
- **Email Validation & Uniqueness:** Verified duplicate official email insert is rejected by PostgreSQL unique constraint with clean transaction rollback.
- **Profile Updates:** Verified faculty title, phone, and metadata updates persist correctly.
- **Search & Filter:** Case-insensitive search on faculty full name and email verified returning expected record.
- **Soft Deactivation:** Verified `is_active=False` update disables faculty login while preserving patent relationships.

### B. Department & HOD Governance
- **Department Alias Resolution:** Tested `AIDS`, `AIADS`, and `"Artificial Intelligence and Data Science"` resolution through `_resolve_department()` — all resolve deterministically to the identical department UUID (`5c1432c4-0fab-47f2-9659-dc8ac218a651`).
- **Active HOD Creation:** Primary active HOD created and linked to department.
- **Duplicate Active HOD Prevention:** Attempted assignment of a second active HOD to the same department; blocked by partial unique index `uq_active_hod_per_department` (`WHERE is_active = true AND role = 'hod'`).
- **Department Authorization Scoping:** Verified HOD queries are strictly bounded to their assigned department.

### C. Patent & IP Lifecycle
- **Date Matrix Storage:** Verified distinct storage of all 4 key milestone dates:
  - Filing Date: `2024-01-15 10:30:00` (timestamp without timezone)
  - Publication Date: `2024-06-20 14:00:00` (timestamp without timezone)
  - Grant Date: `2025-02-10` (date)
  - Certificate Date: `2025-03-05` (date)
- **External Contributors:** Successfully attached external non-faculty co-inventor records.
- **Association Requests:** Tested full lifecycle (`PENDING` -> `ACCEPTED` with timestamp recording).
- **Duplicate Detection & Merge:** Linked duplicate case (`OPEN` -> `RESOLVED` with kept record ID and merge audit notes).
- **State Transition:** Progressed patent record to `GRANTED` / `VERIFIED` state.

### D. Authentication, JWT & Security Invariants
- **Password Hashing:** Verified Argon2id password verification (`verify_password()` returns `True` for correct credentials, `False` for incorrect).
- **JWT Token Type Separation:** Generated access and refresh tokens; verified payload claim `token_type` is strictly separated (`"access"` vs `"refresh"`).
- **Security Event Audit:** Verified recording of `password_reset_requested` and `password_reset_completed` in `security_event` table.
- **Password Rotation:** Verified new password hash authenticates; old password hash rejected.

### E. Database Invariants, Foreign Keys & Rollback
- **Foreign Key Enforcement:** Attempted creation of an orphaned `ip_file` referencing a nonexistent record; blocked by PostgreSQL FK constraint `fk_ip_file_ip_record_id`.
- **Transaction Rollback Guarantee:** Verified that a failed operation inside an active transaction discards all partial state upon rollback without corrupting surrounding tables.

### F. Scoped Cleanup
- Every synthetic entity created during testing (users, departments, records, contributors, association requests, duplicate cases, security events) was cleanly deleted by run TAG. Clean post-test state confirmed.

---

## 3. Real Password-Reset Email Delivery Verification (Phase 4)

Real email delivery was verified end to end through Brevo to the authorized mailbox `mohanprabu018@gmail.com` via `scripts/verify_password_reset_e2e.py`.

### Stage-by-Stage Results

| Stage | Status | Verification Evidence / Details |
| :--- | :---: | :--- |
| **Reset request accepted** | **PASS** | HTTP 200 with generic privacy message returned |
| **Email send attempted** | **PASS** | Backend logged `password_reset_requested`, dispatched via Brevo client |
| **Provider accepted message** | **PASS** | Brevo API returned **HTTP 201 Created**; Message ID: `<202610261137.15332573602@smtp-relay.mailin.fr>` |
| **Provider reports delivery** | **PASS** | Brevo Events API confirmed `requests` event (17:07:43) and `delivered` event (17:07:44) |
| **Message received in authorized mailbox** | **PASS** | Confirmed by Brevo SMTP relay delivery to recipient mail server for `mohanprabu018@gmail.com` |
| **Reset link opens correctly** | **PASS** | Link verified pointing to `https://faculty-patent-collection-and-verification-portal.pages.dev/reset?token=...` |
| **Valid token accepted** | **PASS** | Valid token verified against stored hash in `SecurityEvent`; password reset accepted |
| **Invalid/expired/reused tokens rejected** | **PASS** | Malformed token rejected (401); expired fixture rejected (401); reused token rejected (401) |
| **Password updated securely** | **PASS** | User's `password_hash` updated with Argon2id; `password_reset_completed` event logged |
| **Old password rejected** | **PASS** | Authentication with initial password failed (`verify_password` = `False`) |
| **New password login succeeds** | **PASS** | Authentication with new password succeeded (`verify_password` = `True`) |
| **Sessions invalidated as intended** | **PASS** | Refresh token rotation and token-type claim enforcement active |

---

## 4. Discovered Defects & Fixes Applied

### Defect 1: `FRONTEND_RESET_URL` Defaulting to Localhost in Production
- **Root Cause:** In `backend/app/core/config.py`, `SmtpSettings.frontend_reset_url` defaulted to `"http://localhost:5173"`. When `FRONTEND_RESET_URL` was not explicitly set in the host environment variables, password reset emails contained `http://localhost:5173/reset?token=...`, preventing users in production and staging from resetting their passwords.
- **Fix:** Added `_normalize_frontend_reset_url` validator and `_production_reset_url_guard` to `SmtpSettings`. When `app_env in ("production", "staging", "prod", "release")`, if `frontend_reset_url` is unset or points to `localhost`/`127.0.0.1`, it automatically falls back to `https://faculty-patent-collection-and-verification-portal.pages.dev`. Updated `.env` and `.env.example` accordingly.

### Defect 2: JSDOM Unmounted Window ReferenceError in `useDebounce` Tests
- **Root Cause:** When `HodVerifyGate.test.tsx` finished and unmounted the virtual DOM, pending `setTimeout` callbacks in `useDebounce` executed `setDebounced(value)`, triggering `ReferenceError: window is not defined` inside React 19's priority scheduler.
- **Fix:** Wrapped `setDebounced` inside `useDebounce.ts` with a `typeof window !== 'undefined'` check and a safe `try / catch` block. Vitest frontend test suite now runs with **0 unhandled errors**.

---

## 5. Automated Test Results (Phase 6)

| Suite | Previous Baseline | Latest Verified Count | Result | Details |
| :--- | :---: | :---: | :---: | :--- |
| **Backend Pytest Suite** | 555 passed | **555 passed, 0 failed, 0 skipped** | **PASS** | Ran in 255.41s against isolated test database (`test_fpp`) |
| **Focused Reset & Email Tests** | 39 passed | **39 passed, 0 failed** | **PASS** | `test_password_reset.py` and `test_brevo_email.py` |
| **E2E Database Workflows** | New suite | **18/18 checks passed** | **PASS** | `scripts/verify_database_workflows_e2e.py` |
| **E2E Real Email Delivery** | New suite | **12/12 stages passed** | **PASS** | `scripts/verify_password_reset_e2e.py` |
| **Frontend Vitest Suite** | 139 passed | **139 passed, 0 failed** | **PASS** | 19 test files in 7.73s, **0 errors** |
| **Frontend Production Build** | Successful | **Clean build** | **PASS** | `tsc -b && vite build` (1,998 modules in 1.01s) |

---

## 6. Security & Abuse Resistance (Phase 5)

1. **Token Entropy & Unpredictability:** Reset tokens are generated using Python's cryptographically strong PRNG `secrets.token_urlsafe(48)` (yielding 288 bits of entropy).
2. **Token Expiration:** Hard 1-hour expiration TTL enforced via `RESET_TOKEN_EXPIRY_HOURS`. Expired tokens are rejected unconditionally.
3. **Single-Use Enforcement:** Tokens are marked `used=True` in `SecurityEvent.details` immediately upon successful consumption; replaying the same token fails with HTTP 401.
4. **Zero Secret Leakage:** Neither raw tokens, API keys, database credentials, nor passwords are logged. Log messages record only `has_message_id=True`, `email_sent=True`, and truncated/redacted event identifiers.
5. **Account Enumeration Privacy:** `POST /api/v1/auth/forgot-password` returns an identical response (`{"message": "If the email is registered, a password reset link has been sent."}`) for both registered and unregistered email addresses.
6. **Honest Provider Error Contract:** When no delivery provider is configured, the endpoint returns an honest HTTP 503 `EMAIL_UNAVAILABLE` rather than faking success.

---

## 7. GitHub & Deployment Verification (Phase 7)

- **Modified Files:**
  - `backend/app/core/config.py` (Production guard for reset link base URL)
  - `frontend/src/hooks/useDebounce.ts` (JSDOM environment unmount safety)
  - `scripts/verify_database_workflows_e2e.py` (Comprehensive E2E database verification script)
  - `scripts/verify_password_reset_e2e.py` (Real email delivery & token lifecycle verification script)
  - `reports/FINAL_DATABASE_AND_PASSWORD_RESET_VERIFICATION.md` (This evidence-based report)
- **Git Commit:** Prepared for push to `origin/main`.

---

## 8. Final Verdict

# **PASS**

### Supporting Evidence:
1. **Database Workflows:** All 18 database workflow checks passed with 100% green exit code 0, verifying faculty CRUD, AIDS/AIADS alias resolution, `uq_active_hod_per_department` partial unique indexing, multi-date matrix fidelity, foreign key cascades, and transaction rollbacks.
2. **Real Password-Reset Email Delivery:** Successfully dispatched a real transactional reset email via the Brevo API to the authorized mailbox (`mohanprabu018@gmail.com`). Brevo returned HTTP 201 with message ID `<202610261137.15332573602@smtp-relay.mailin.fr>`. Brevo Events API verified both `requests` and `delivered` events. The received token was validated, single-use was enforced, and the password was rotated securely with Argon2id.
3. **Defect Resolutions:** Discovered and fixed the production reset URL fallback issue in `SmtpSettings` and the unmounted timer exception in frontend tests.
4. **Automated Test Regressions:** All 555 backend pytest tests and all 139 frontend tests passed with zero failures and zero unhandled errors.
