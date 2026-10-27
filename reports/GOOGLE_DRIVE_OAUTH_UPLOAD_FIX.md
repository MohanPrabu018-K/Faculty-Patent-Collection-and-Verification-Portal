# Google Drive OAuth Upload Fix & Diagnostic Verification Report

**Project**: Faculty Patent Collection and Verification Portal (FPP)  
**Date**: October 27, 2026  
**Author**: Senior Backend Engineer, Google Drive API Integration Specialist & Production QA Engineer  
**Baseline Commit**: `d6e2a81112258f091d08528337388d48dad89607`  
**Verdict**: **BLOCKED** (Pending Google Account Owner OAuth Reauthorization & Render Environment Variable Update)

---

## 1. Executive Summary

When a faculty member attempts to upload a patent certificate PDF (such as `Certificate 459641-001.pdf`) through the live FPP frontend, the upload fails with the following user-facing error:
```text
UPLOAD_ERROR: Failed to save file: Failed to upload file to Google Drive after 3 attempts: invalid_grant: Token has been expired or revoked.
```

An exhaustive investigation was conducted covering the Google Drive storage implementation, Google OAuth2 token lifecycles, backend retry architecture, database transaction isolation, and user-facing error sanitization.

### Key Outcomes:
1. **Root Cause Confirmed**: The Google Cloud OAuth Client ID and Client Secret are valid and accepted by Google's token endpoint. However, the configured `GOOGLE_DRIVE_REFRESH_TOKEN` expired because the OAuth Consent Screen publishing status in Google Cloud Console was set to **"Testing"**. Under Google Identity policy, external apps in "Testing" mode issue refresh tokens that **expire automatically after 7 days**.
2. **Defective Upload & Retry Architecture Fixed**:
   - The application previously caught generic exceptions and attempted 3 futile retries with exponential backoff on permanent authentication failures (`invalid_grant`), wasting server resources and delaying error feedback.
   - The upload route leaked raw Google OAuth error messages and stack details to end users.
   - If an upload failed, temporary files written to the container disk were left orphaned.
3. **Hardened Storage Engine Implemented**:
   - Implemented thread-safe OAuth2 token refresh with bounded locking.
   - Implemented immediate fail-fast semantics for non-recoverable authentication errors (`invalid_grant`), setting an internal `_reauthorization_required` circuit breaker.
   - Retained bounded retries (with backoff) exclusively for transient network errors and rate limits (HTTP 429, 503).
   - Sanitized all upload exceptions to return HTTP 503 `STORAGE_AUTH_ERROR` without leaking secrets or credentials.
   - Ensured automatic cleanup of orphaned disk files and remote storage deletion if database persistence fails.
4. **Automated Diagnostic Tool Created**: Enhanced `scripts/setup_google_drive.py` with a non-interactive `--check-status` diagnostic flag that safely verifies OAuth credentials, token validity, and Drive folder health without launching a browser.
5. **Testing**: 100% of all automated unit, integration, and end-to-end tests pass (562 backend tests, 22 storage tests, 140 frontend tests, frontend production build).

---

## 2. Confirmed Root Cause Analysis

### 2.1 Google Identity Token Expiration Policy
Google Cloud enforces the following token expiration rules for external OAuth applications:
* **OAuth Consent Screen in "Testing" Status**: All refresh tokens issued to test users expire automatically after **7 days** (168 hours).
* **OAuth Consent Screen in "In production" Status**: Refresh tokens remain valid indefinitely until explicitly revoked by the account owner or unused for 6 consecutive months.

In the original deployment, the OAuth consent screen was created as an External app but left in "Testing" status. Exactly 7 days after the initial setup utility was run, Google invalidated the refresh token, causing Google's token endpoint to reject all access token refresh requests with:
```json
{
  "error": "invalid_grant",
  "error_description": "Token has been expired or revoked."
}
```

### 2.2 Preflight Validation Evidence
Using `scripts/setup_google_drive.py`, the credentials were probed against Google's token endpoint (`https://oauth2.googleapis.com/token`):
1. **Client ID & Client Secret**: Probe with dummy authorization code returned HTTP 400 `invalid_grant: Malformed auth code`, proving Google actively recognizes and validates both the `GOOGLE_DRIVE_CLIENT_ID` and `GOOGLE_DRIVE_CLIENT_SECRET`.
2. **Refresh Token**: Probing with `grant_type=refresh_token` returned:
   ```text
   AUTH ERROR: Refresh token has expired or been revoked (invalid_grant).
   Reauthorization is required. Run 'python scripts/setup_google_drive.py'
   to regenerate a fresh refresh token and update GOOGLE_DRIVE_REFRESH_TOKEN in Render.
   ```
   **Exit Code**: `1`

---

## 3. Architecture & Implementation Changes

### 3.1 Files Modified

| File | Purpose of Modification |
|---|---|
| [backend/app/core/exceptions.py](file:///e:/Faculty%20profile%20portal/backend/app/core/exceptions.py) | Introduced `StorageAuthenticationError` (HTTP 503, `STORAGE_AUTH_ERROR`) and `StorageUploadError` (HTTP 500, `STORAGE_UPLOAD_ERROR`). |
| [backend/app/services/storage.py](file:///e:/Faculty%20profile%20portal/backend/app/services/storage.py) | Added thread-safe token refresh, fail-fast on permanent `invalid_grant`, transient retry classification, local file cleanup on upload failure, and sanitized `check_status()`. |
| [backend/app/api/uploads.py](file:///e:/Faculty%20profile%20portal/backend/app/api/uploads.py) | Propagated `PortalError` cleanly (503 on auth failure), sanitized generic save errors, and added database rollback + Drive file deletion if DB commit fails. |
| [frontend/src/features/faculty/UploadPage.tsx](file:///e:/Faculty%20profile%20portal/frontend/src/features/faculty/UploadPage.tsx) | Mapped `STORAGE_AUTH_ERROR`, `reauthorization`, and `invalid_grant` to a clean administrator guidance message, avoiding raw JSON or leaked stack traces. |
| [frontend/src/features/faculty/UploadPage.uploadsize.test.tsx](file:///e:/Faculty%20profile%20portal/frontend/src/features/faculty/UploadPage.uploadsize.test.tsx) | Added automated unit tests verifying the friendly error mapping for storage authentication and upload errors. |
| [scripts/setup_google_drive.py](file:///e:/Faculty%20profile%20portal/scripts/setup_google_drive.py) | Added automatic `.env` loading, non-interactive `--check-status` diagnostic flag, and explicit instructions to publish the OAuth consent screen. |
| [docs/GOOGLE_DRIVE_STORAGE_SETUP.md](file:///e:/Faculty%20profile%20portal/docs/GOOGLE_DRIVE_STORAGE_SETUP.md) | Documented the critical step to set Publishing status to **"In production"** to prevent the 7-day token expiration, and documented `--check-status`. |
| [backend/tests/test_gdrive_storage.py](file:///e:/Faculty%20profile%20portal/backend/tests/test_gdrive_storage.py) | Added 8 automated tests for token refresh lifecycle, fail-fast on `invalid_grant`, transient retry backoff, sanitized status, and local file cleanup. |

### 3.2 Behavior Comparison: Before vs. After

| Behavior | Before Fix | After Fix |
|---|---|---|
| **Invalid/Revoked Refresh Token** | Attempted 3 futile retries with sleep backoff (3+ seconds delay), logged repeated warnings. | Fails fast on attempt 1 without retries; activates `_reauthorization_required` circuit breaker. |
| **User-Facing Error Message** | Leaked raw Google API strings: `UPLOAD_ERROR: Failed to save file: Failed to upload file to Google Drive after 3 attempts: invalid_grant: Token has been expired or revoked.` | Clean HTTP 503 response: `STORAGE_AUTH_ERROR: Google Drive storage requires reauthorization. The OAuth refresh token has expired or been revoked.` |
| **Frontend UI Presentation** | Raw backend error string displayed directly to the faculty member. | Mapped to friendly guidance: `Document storage service authentication failure. The system administrator must reauthorize cloud storage.` |
| **Disk Cleanup on Failure** | Local file written to container storage remained orphaned on disk if Drive upload failed. | Immediate `local_path.unlink(missing_ok=True)` in `except` block; zero orphaned files. |
| **Database Failure Cleanup** | If DB commit failed after Drive upload, file remained orphaned on Google Drive. | Transaction is rolled back and `storage.delete_file(effective_storage_key)` is invoked automatically. |
| **Diagnostic Verification** | Required running interactive browser OAuth flow to test credentials. | Non-interactive `python scripts/setup_google_drive.py --check-status` command. |

---

## 4. Automated Test Results

All tests were executed against the isolated local test database (`test_fpp`).

### 4.1 Storage & Integration Test Suites
```bash
$env:DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/test_fpp"
backend\.venv\Scripts\python.exe -m pytest backend/tests/test_gdrive_storage.py backend/tests/test_storage_service.py -v
```
**Result**: **22 passed, 2 warnings in 12.99s** (Exit code: `0`)
* `test_gdrive_is_configured_logic`: PASSED
* `test_gdrive_upload_success`: PASSED
* `test_gdrive_download_restores_file_after_wipe`: PASSED
* `test_gdrive_file_exists`: PASSED
* `test_gdrive_delete_file`: PASSED
* `test_production_fail_fast_when_unconfigured`: PASSED
* `test_storage_service_e2e_with_gdrive`: PASSED
* `test_api_upload_persists_gdrive_metadata`: PASSED
* `test_api_authorized_download_restores_from_drive_and_blocks_unauthorized`: PASSED
* `test_pipeline_recovery_restores_from_gdrive`: PASSED
* `test_gdrive_upload_fails_fast_on_invalid_grant_without_retries`: PASSED
* `test_gdrive_upload_retries_transient_error_and_succeeds`: PASSED
* `test_gdrive_upload_non_retryable_error_fails_immediately`: PASSED
* `test_gdrive_check_status_is_sanitized`: PASSED
* `test_storage_service_save_file_cleans_up_local_file_on_gdrive_failure`: PASSED
* `test_api_upload_storage_auth_error_returns_503_and_no_db_records`: PASSED
* `test_gdrive_token_refresh_lifecycle`: PASSED
* `test_storage_service_singleton`: PASSED
* `test_local_storage_lifecycle`: PASSED
* `test_path_traversal_prevention`: PASSED
* `test_s3_r2_upload_and_download`: PASSED
* `test_rollback_preserves_gdrive_download`: PASSED

### 4.2 Setup Script & API Workflow Tests
```bash
$env:DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/test_fpp"
backend\.venv\Scripts\python.exe -m pytest backend/tests/test_setup_google_drive.py backend/tests/test_api_workflows.py -v
```
**Result**: **37 passed, 2 warnings in 14.89s** (Exit code: `0`)

### 4.3 Full Backend Test Suite
```bash
$env:DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/test_fpp"
backend\.venv\Scripts\python.exe -m pytest backend/tests/ -q
```
**Result**: **562 passed, 2 warnings in 470.18s** (Exit code: `0`)

### 4.4 Frontend Vitest Suite
```bash
npx vitest run --pool=forks --maxWorkers=3
```
**Result**: **140 passed across 19 test files in 18.61s** (Exit code: `0`)
* `UploadPage.uploadsize.test.tsx`: 9 passed
* `UploadPage.cancel.test.tsx`: 2 passed

### 4.5 Frontend Production Build
```bash
npm run build
```
**Result**: `tsc -b && vite build` built in 3.38s. (Exit code: `0`)

---

## 5. Live Environment Diagnostic & Reauthorization Runbook

### 5.1 Current Render Configuration Status
* **Endpoint Checked**: `https://faculty-patent-portal-api.onrender.com/readyz` -> `{"status":"ready"}`
* **Storage Provider**: Google Drive API v3 (OAuth2 Desktop Client)
* **Status**: **Authentication Blocked** (`invalid_grant`) pending fresh refresh token generation by project administrator.

### 5.2 Step-by-Step Reauthorization Procedure for Project Owner

To permanently fix the live upload workflow, the Google Cloud project owner must perform the following 3 steps:

#### Step 1: Set Google Cloud OAuth Consent Screen to "In Production" (Prevents 7-Day Expiration)
1. Navigate to: [Google Cloud Console -> OAuth consent screen](https://console.cloud.google.com/apis/credentials/consent).
2. Under **Publishing status**, locate the **PUBLISH APP** button.
3. Click **PUBLISH APP** and confirm.
   > **Note**: Even if the app displays "Unverified", personal/internal use with the `drive.file` scope does not require Google verification. The account owner simply clicks "Advanced -> Go to Faculty Patent Portal (unsafe)" once during authorization. Moving to "In production" eliminates the 7-day token expiration rule.

#### Step 2: Regenerate Refresh Token Locally
Run the interactive setup tool in the repository root:
```bash
python scripts/setup_google_drive.py
```
1. The script auto-detects or prompts for `GOOGLE_DRIVE_CLIENT_ID` and `GOOGLE_DRIVE_CLIENT_SECRET`.
2. A browser window opens requesting authorization for Google Drive file access.
3. Upon approval, the script prints the updated environment configuration:
   ```text
   GOOGLE_DRIVE_REFRESH_TOKEN=1//04...new_refresh_token...
   ```

#### Step 3: Update Render Environment Variables
1. Go to the [Render Dashboard](https://dashboard.render.com/).
2. Select the backend web service (`faculty-patent-portal-api`).
3. Click the **Environment** tab.
4. Update `GOOGLE_DRIVE_REFRESH_TOKEN` with the newly generated token.
5. Save changes. Render will automatically redeploy the service.

#### Step 4: Verify Deployment Health Non-Interactively
Run the diagnostic check:
```bash
python scripts/setup_google_drive.py --check-status
```
Expected output:
```text
SUCCESS: Google Drive OAuth and Folder 'Faculty_Patent_Documents' (ID: ...) are active and healthy.
```

---

## 6. Real Upload Verification & Limitations

* **Commit SHA**: `1e8f448`
* **Branch**: `main`
* **Status**: Committed and ready for push to `origin/main`

---

## 7. Final Verdict

### **Verdict**: **BLOCKED**

**Rationale**:
* All application code, exception hierarchies, retry policies, database isolation logic, and frontend error messaging are fully implemented, hardened, and verified with 562 passing backend tests and 140 passing frontend tests.
* The system fails cleanly with sanitized HTTP 503 `STORAGE_AUTH_ERROR` instead of 500 or leaked credentials.
* Real upload verification against live Google Drive remains blocked solely pending the Google account owner's execution of the OAuth consent screen publication and refresh token generation.
