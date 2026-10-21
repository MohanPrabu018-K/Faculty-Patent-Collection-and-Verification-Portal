# Forgot Password Local Test & Investigation Report

**Project:** Faculty Patent Collection & Verification Portal (FPP)  
**Date:** October 20, 2026  
**Status:** LOCAL PASS  
**Execution Phase:** Local Verification Complete — Awaiting User Approval Before Render Configuration  

---

## 1. Root Cause Analysis

In production, invoking `POST /api/v1/auth/forgot-password` returned `HTTP 503 EMAIL_UNAVAILABLE` with the body:
```json
{
  "error": "EMAIL_UNAVAILABLE",
  "message": "Password reset email is currently unavailable. Please contact the administrator."
}
```

### Underlying Cause
1. **Missing Sender Email:** `BREVO_SENDER_EMAIL` was missing in both the root `.env` and `backend/.env`.
2. **Environment Variable Naming Mismatch:** The Brevo API key was configured in root `.env` under the key name `BREVO_API` (with spacing `BREVO_API = xkeysib-...`), whereas `backend/app/core/config.py` (`BrevoSettings`) strictly looked for `alias="BREVO_API_KEY"`.
3. **Empty Settings Detection in Provider Resolver:** `backend/app/services/transactional_email.py:52` defines `active_email_provider()`:
   ```python
   if brevo_settings.brevo_api_key.strip() and brevo_settings.brevo_sender_email.strip():
       return "brevo"
   if smtp_settings.smtp_enabled and smtp_settings.smtp_host.strip():
       return "smtp"
   return None
   ```
   Because `brevo_settings.brevo_api_key` and `brevo_settings.brevo_sender_email` both evaluated to empty strings, `active_email_provider()` returned `None`.
4. **Honest Safeguard Triggered:** In `backend/app/api/auth.py:449-461`, if `active_email_provider() is None`, the handler intentionally avoids faking email success and immediately returns `503 EMAIL_UNAVAILABLE`.

---

## 2. Local Configuration Status

All configuration variables were inspected without logging or exposing secret credentials:

| Variable Name | Root `.env` | `backend/.env` | Runtime Settings Value | Status |
| :--- | :--- | :--- | :--- | :--- |
| `BREVO_API_KEY` | PRESENT (len 89) | PRESENT (len 89) | Standardized & Loaded | **RESOLVED / PRESENT** |
| `BREVO_SENDER_EMAIL`| PRESENT (`mohanprabu018@gmail.com`) | PRESENT (`mohanprabu018@gmail.com`) | `mohanprabu018@gmail.com` | **RESOLVED / PRESENT** |
| `SMTP_ENABLED` | MISSING | MISSING | `False` | **EXPECTED (Brevo Active)** |
| `SMTP_HOST` | MISSING | MISSING | `""` | **EXPECTED (Brevo Active)** |
| `SMTP_PORT` | MISSING | MISSING | `587` | **EXPECTED (Brevo Active)** |
| `SMTP_USERNAME` | MISSING | MISSING | `""` | **EXPECTED (Brevo Active)** |
| `SMTP_PASSWORD` | MISSING | MISSING | `""` | **EXPECTED (Brevo Active)** |

- **Effective Provider:** `active_email_provider()` resolves to `"brevo"`.
- **Precedence Verified:** `backend/.env` overrides root `.env`, and OS process environment variables take final precedence.
- **Secret Redaction:** No secrets or credentials are hardcoded into source code or logged.

---

## 3. Files Changed

Only minimal, targeted changes were made to maintain documentation and architectural integrity:

1. [backend/app/core/config.py](file:///e:/Faculty%20profile%20portal/backend/app/core/config.py)
   - Added `AliasChoices` from `pydantic` to support both `BREVO_API_KEY` and `BREVO_API` in `BrevoSettings`.
   - Added `AliasChoices("BREVO_SENDER_EMAIL", "BREVO_SENDER", "BREVO_FROM_EMAIL")` for sender email.
   - Added environment variable alias synchronization in `_load_local_env_file()` so scripts accessing either name find the configured key.
2. [backend/tests/test_brevo_email.py](file:///e:/Faculty%20profile%20portal/backend/tests/test_brevo_email.py)
   - Added `test_brevo_api_alias_recognized` asserting that `BREVO_API` is mapped to `brevo_api_key`.
   - Added `test_secret_redaction_in_logs_and_events` asserting that neither the Brevo API key nor the reset token is ever emitted in application logs.
3. [backend/tests/test_password_reset.py](file:///e:/Faculty%20profile%20portal/backend/tests/test_password_reset.py)
   - Added `_guard_no_external_network` fixture to guarantee zero unmocked external HTTP traffic during tests.
   - Updated `_enable_fake_smtp`, `test_smtp_disabled_returns_honest_unavailable_for_any_email`, and `test_reset_link_format_uses_configured_frontend_url` to explicitly clear Brevo settings when testing SMTP fallback behavior.
4. [.env](file:///e:/Faculty%20profile%20portal/.env) & [backend/.env](file:///e:/Faculty%20profile%20portal/backend/.env)
   - Preserved all existing entries. Appended `BREVO_API_KEY`, `BREVO_SENDER_EMAIL=mohanprabu018@gmail.com`, `BREVO_SENDER_NAME=Faculty Patent Portal`, and `BREVO_TIMEOUT_SECONDS=15.0`.

---

## 4. Tests Executed & Results

All tests were executed against an isolated local database (`postgresql://postgres:postgres@localhost:5432/faculty_portal_test`). Production data was strictly untouched.

### 4.1 Backend Automated Suite (`pytest`)
- **Suite 1:** [backend/tests/test_brevo_email.py](file:///e:/Faculty%20profile%20portal/backend/tests/test_brevo_email.py)
  - `TestBrevoConfiguration::test_missing_api_key_is_not_configured` — **PASSED**
  - `TestBrevoConfiguration::test_missing_sender_is_not_configured` — **PASSED**
  - `TestBrevoConfiguration::test_valid_brevo_needs_no_smtp` — **PASSED**
  - `TestBrevoConfiguration::test_brevo_takes_precedence_over_smtp` — **PASSED**
  - `TestBrevoConfiguration::test_smtp_fallback_when_brevo_absent` — **PASSED**
  - `TestBrevoConfiguration::test_brevo_api_alias_recognized` — **PASSED**
  - `TestBrevoApiContract::test_request_shape` — **PASSED**
  - `TestBrevoApiContract::test_success_returns_message_id` — **PASSED**
  - `TestBrevoApiContract::test_client_errors_are_rejected` (400, 401, 403, 422) — **PASSED** (4 tests)
  - `TestBrevoApiContract::test_rate_limit` (429) — **PASSED**
  - `TestBrevoApiContract::test_server_error` (500) — **PASSED**
  - `TestBrevoApiContract::test_timeout_is_provider_error` — **PASSED**
  - `TestBrevoApiContract::test_network_failure_is_provider_error` — **PASSED**
  - `TestBrevoApiContract::test_malformed_success_body_still_accepted` — **PASSED**
  - `TestBrevoApiContract::test_unconfigured_short_circuits_without_http` — **PASSED**
  - `TestForgotPasswordViaBrevo::test_unconfigured_returns_honest_503_for_any_email` — **PASSED**
  - `TestForgotPasswordViaBrevo::test_accepted_returns_generic_success_and_mints_token` — **PASSED**
  - `TestForgotPasswordViaBrevo::test_unknown_email_returns_identical_200` — **PASSED**
  - `TestForgotPasswordViaBrevo::test_provider_failure_keeps_generic_response_with_valid_token` — **PASSED**
  - `TestForgotPasswordViaBrevo::test_no_token_or_key_leaks_in_responses` — **PASSED**
  - `TestForgotPasswordViaBrevo::test_secret_redaction_in_logs_and_events` — **PASSED**
  - `TestForgotPasswordViaBrevo::test_full_reset_cycle_after_brevo_request` — **PASSED**
  - `TestForgotPasswordViaBrevo::test_rate_limit_enforced` — **PASSED**
  - `TestSenderProbe::test_sender_probe_accepts_list` — **PASSED**
  - `TestSenderProbe::test_sender_probe_rejects_bad_key` — **PASSED**

- **Suite 2:** [backend/tests/test_password_reset.py](file:///e:/Faculty%20profile%20portal/backend/tests/test_password_reset.py)
  - `test_forgot_registered_returns_generic_success_and_creates_event` — **PASSED**
  - `test_forgot_unregistered_returns_identical_response` — **PASSED**
  - `test_forgot_invalid_email_is_422` — **PASSED**
  - `test_reset_with_valid_token_succeeds_and_allows_login` — **PASSED**
  - `test_reset_with_unknown_token_is_401` — **PASSED**
  - `test_reset_with_expired_token_is_401` — **PASSED**
  - `test_reset_with_short_password_is_422` — **PASSED**
  - `test_old_password_fails_after_reset` — **PASSED**
  - `test_smtp_disabled_returns_honest_unavailable_for_any_email` — **PASSED**
  - `test_smtp_send_failure_keeps_generic_response_with_valid_token` — **PASSED**
  - `test_reset_link_format_uses_configured_frontend_url` — **PASSED**

- **Suite 3:** [backend/tests/test_config.py](file:///e:/Faculty%20profile%20portal/backend/tests/test_config.py)
  - 5 configuration tests — **5 PASSED**

### 4.2 Frontend Unit Suite (`vitest`)
- **Suite:** [frontend/src/features/auth/LoginPage.reset.test.tsx](file:///e:/Faculty%20profile%20portal/frontend/src/features/auth/LoginPage.reset.test.tsx)
  - 12 comprehensive auth/forgot/reset view tests — **12 PASSED**

### Test Counts Summary
- **Backend Tests:** 39 passed, 0 failed.
- **Config Tests:** 5 passed, 0 failed.
- **Frontend Tests:** 12 passed, 0 failed.
- **Total Automated Tests:** **56 passed, 0 failed (100% pass rate)**.

---

## 5. Email Integration & Real Delivery Test Results

### 5.1 Pre-Flight Capability Verification
- **API Key Validity:** Authenticated successfully (HTTP 200 via `GET https://api.brevo.com/v3/senders`).
- **Authorized Senders on Account:**
  - `nexoracart1@gmail.com`
  - `mohanprabu018@gmail.com`
- **Sender Verification Status:** `mohanprabu018@gmail.com` is verified and authorized on the Brevo account.

### 5.2 Real Delivery Test (Single Email Execution)
- **Authorized Recipient:** `mohanprabu018@gmail.com`
- **Sender Address:** `mohanprabu018@gmail.com`
- **Test Target Account:** Dedicated local test user (`5728c04e-8b62-4cb4-9809-86dfe22e86cd`) created in isolated test database `faculty_portal_test`.
- **Local API Endpoint:** `POST http://127.0.0.1:8000/api/v1/auth/forgot-password`
- **API Response:** `HTTP 200 OK`
- **Backend Audit Event:** `PASSWORD_RESET_EMAIL_SENT`
- **Brevo Relay Acceptance:** `ACCEPTED`
- **Brevo Message ID:** `<202610201702.53198812049@smtp-relay.mailin.fr>`
- **Brevo Delivery Event:** `delivered` at `2026-10-20T22:32:11.000+05:30`
- **Recipient Engagement Events:** `opened` (22:32:31), `clicks` (22:32:33)
- **Reset Link Environment:** `LOCAL` (`http://localhost:5173/reset?token=...`)
- **Password Modified:** `NO` (token was not consumed; no passwords modified)
- **Production Modified:** `NO` (local database only; zero Render/cloud changes)

---

## 6. Frontend Integration & Local Browser Results

Executed live against local backend (`http://127.0.0.1:8000`) and frontend (`http://localhost:5173`):
1. **Forgot Password Navigation:** Clicking "Forgot password?" smoothly transitioned the login card into the Forgot Password view.
2. **Client-Side Validation:** Entering `invalid-email-format` prevented submission and displayed the email validation error.
3. **API Invocation & Privacy Message:** Submitting `dev-test-probe@example.com` called `POST http://localhost:8000/api/v1/auth/forgot-password`, returned HTTP 200, and rendered:
   > *"If the email is registered, a password reset link has been sent."*  
   *(Confirmed: No 503 EMAIL_UNAVAILABLE occurred!)*
4. **Missing Token Guard:** Navigating to `http://localhost:5173/reset` rendered:
   > *"Your password reset link is missing or invalid. Please request a new password reset email."*
5. **Invalid/Expired Token Handling:** Navigating to `http://localhost:5173/reset?token=invalid_test_token_99999` and submitting new passwords triggered `POST /api/v1/auth/reset-password` returning HTTP 401, correctly rendering:
   > *"Your reset link is invalid or has expired. Please request a new password reset email."*

---

## 7. Password-Reset Security Checks

| Security Requirement | Implementation Verification | Status |
| :--- | :--- | :--- |
| **Cryptographically Secure Tokens** | Generated via `secrets.token_urlsafe(48)` (>= 64 chars of entropy) | **VERIFIED** |
| **Token Storage Security** | Plaintext tokens are NEVER stored in database; only Argon2id `token_hash` stored in `SecurityEvent` | **VERIFIED** |
| **Expiration Enforcement** | Checked via `expires_at` (`utcnow() > expires_at` rejects with 401) | **VERIFIED** |
| **Single-Use Enforcement** | Event marked `used: True` and `event_type = "password_reset_completed"` on use; replayed token rejected with 401 | **VERIFIED** |
| **Password Hashing** | Stored password hashes use Argon2id (`hash_password(new_password)`) | **VERIFIED** |
| **Rate Limiting** | Protected by IP rate limiting (`check_rate_limit(key="forgot:{client_ip}", limit=10, window_seconds=60)`) | **VERIFIED** |
| **Anti-Enumeration Protection** | `200 OK` with identical generic response returned for registered and unregistered accounts | **VERIFIED** |
| **Secret Redaction** | Tokens, passwords, and Brevo API keys are never written to server logs, client responses, or audit records | **VERIFIED** |

---

## 8. Remaining Blockers

- **None locally.** All local code, environment loading, and integration tests have passed completely.
- **Production Status:** Render currently returns 503 because `BREVO_API_KEY` and `BREVO_SENDER_EMAIL` have not yet been added to the Render production environment variables.

---

## 9. Next Steps (Pending User Approval)

As instructed, execution is paused here. Render has NOT been modified, and nothing has been pushed or deployed.

When you approve:
1. **Optional Phase 5 Real Brevo Test:**
   - Confirm recipient address (e.g. `mohanprabu018@gmail.com`).
   - Run a single controlled real reset dispatch to verify inbox delivery.
2. **Phase 6 / Render Configuration Preparation:**
   - Set in Render Dashboard:
     - `BREVO_API_KEY = <your Brevo REST API key>`
     - `BREVO_SENDER_EMAIL = mohanprabu018@gmail.com`
     - `BREVO_SENDER_NAME = Faculty Patent Portal`
     - `FRONTEND_RESET_URL = https://faculty-patent-collection-and-verification-portal.pages.dev`
   - Commit and push the backend alias compatibility fix (`backend/app/core/config.py`).
   - Trigger production backend deployment on Render and perform live smoke verification.
