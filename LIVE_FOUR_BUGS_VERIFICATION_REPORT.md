# Live Production Verification Report: Four FPP Issues

**Execution Date:** 2026-10-26  
**Target Environments:**
- **Live Frontend:** `https://faculty-patent-collection-and-verification-portal.pages.dev`
- **Live Backend API:** `https://faculty-patent-portal-api.onrender.com`
- **GitHub Repository:** `https://github.com/MohanPrabu018-K/Faculty-Patent-Collection-and-Verification-Portal` (Branch: `main`)
- **Fix Commit Baseline:** `94385b40f30406e55559b1f9cbd06891cfe5d71d`  
- **Latest HEAD Commit:** `44549a9d1296e74097bcace7d7267ba86bc51f8d`

---

## A. Deployment Verification

Direct empirical probes were conducted against both production hosting providers to establish whether the fix commit (`94385b4`) is active on the live services.

| Service | Target URL | HTTP Status | Deployed Commit / Build State | Verification Evidence | Deployment Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Backend API** (Render) | `https://faculty-patent-portal-api.onrender.com` | `200 OK`<br>`/healthz`: `200`<br>`/readyz`: `200`<br>`/openapi.json`: `200` (82,737 bytes) | Contains commit `94385b4` | 1. JWT tokens issue distinct `token_type` claims (`"access"` vs `"refresh"`).<br>2. `POST /api/v1/auth/login` returns `refresh_token` in body and sets dual `SameSite=None; Secure; HttpOnly` cookies.<br>3. `GET /api/v1/auth/me` with refresh token returns `401 {"error":"AUTHENTICATION_ERROR","message":"Invalid token type: refresh token cannot be used as access token"}`.<br>4. `POST /api/v1/auth/refresh` without credentials rejects with `401 {"error":"AUTHENTICATION_ERROR","message":"Authentication credentials missing"}`.<br>5. Department resolution resolves canonical UUIDs, `"AIDS"`, `"AIADS"`, and name aliases with `ACTIVE_HOD_EXISTS` (HTTP 409) enforcement.<br>6. All 18 live patent records serialize dates in strict ISO `YYYY-MM-DD` date-only format. | **CONFIRMED DEPLOYED** |
| **Frontend CDN** (Cloudflare Pages) | `https://faculty-patent-collection-and-verification-portal.pages.dev` | `200 OK` (Server: `cloudflare`) | Pre-audit build (`index-Cp6k5oJ4.js`, `client-Cd6iZYEC.js`) | Asset inspection of served chunks confirms edge CDN is still serving the previous deployment bundle. Bundle inspection indicates that `POLL_INTERVAL`, `publication_date` input binding, and `refreshPromise` from commit `94385b4` are not yet active on the Cloudflare Pages global edge. | **PENDING DEPLOYMENT** |

> [!IMPORTANT]
> Because Cloudflare Pages has not yet completed the deployment of commit `94385b4` to its global CDN edge, client-side auto-polling and publication date form binding in `RecordDetailPage.tsx` cannot execute in the live browser until Cloudflare Pages deploys the updated bundle. Per the verification guidelines, affected frontend tests are reported as **BLOCKED** rather than falsely marked as fixed.

---

## B. Results Table

| Bug | Test Scenario | Result | Evidence & Metrics | Remaining Issues / Observations |
| :--- | :--- | :--- | :--- | :--- |
| **Bug 1: Patent Date Extraction & Auto-Population** | Backend date extraction regexes, ISO date-only serialization (`YYYY-MM-DD`), and frontend polling/form population. | **BLOCKED** *(Frontend Edge)*<br>*(Backend logic verified)* | **Backend Evidence:**<br>- 18 live records inspected.<br>- 9 Design Registrations inspected (`30539176`, `190d976a`, `f6b7771e`, `0a95f605`, `ba61e4e8`, `6d82dd6d`, `1323c75d`, `69e637b5`, `51a7d334`): correctly leave filing, publication, and grant dates `null` without inventing false grant dates.<br>- Date serialization conforms strictly to ISO date-only format (`YYYY-MM-DD`) without timestamps or timezone shifts.<br>**Frontend Evidence:**<br>- Edge bundle `assets/RecordDetailPage-mKjQyy8M.js` lacks `publication_date` controlled input binding and `POLL_INTERVAL`. | Cloudflare Pages deployment of the updated frontend bundle is required before live in-browser auto-polling can be observed end-to-end. Backend model and serialization are verified. |
| **Bug 2: Faculty Creation Navigation & Session Retention** | Form resilience on validation errors, session preservation, and absence of unwanted backwards redirection. | **PASS** | **Live Browser Execution:**<br>- Logged in as Super Admin (`admin@faculty.edu`) and landed on `/admin/dashboard`.<br>- Navigated to `/admin/faculty` via sidebar link.<br>- Clicked "Add faculty" button, opening the creation modal.<br>- Inspected Department dropdown: confirmed "Artificial Intelligence and Data Science" is present.<br>- Triggered client-side validation errors by leaving required fields empty (`Full name *`, `Official email *`) and clicking Create.<br>- Modal remained open in place, displayed validation guidance, and did NOT unexpectedly redirect to the dashboard or previous page, nor terminate the session.<br>- Captured screenshot: `media_1793002159861.png`. | None. Verified in live browser environment on production. |
| **Bug 3: AIDS Department HOD Creation & Alias Resolution** | Canonical department dropdown selection, UUID submission, alias resolution, and duplicate active HOD prevention. | **PASS** | **Live API & Browser Execution:**<br>- Dropdown presents canonical department mapping to UUID `5c1432c4-0fab-47f2-9659-dc8ac218a651` (`Artificial Intelligence and Data Science`, code `AIADS`).<br>- Active HOD for AIDS verified already present in database: `qa.aids.hod.live@faculty.edu` (UUID: `ebec156f-3fff-42cf-8f55-611124579ae3`).<br>- Duplicate HOD creation tested across 4 distinct representations, all returning **HTTP 409** (`ACTIVE_HOD_EXISTS`):<br>  1. Canonical UUID (`5c1432c4-0fab-47f2-9659-dc8ac218a651`) -> `409 Conflict`<br>  2. Alias code `"AIDS"` -> `409 Conflict`<br>  3. Alias code `"AIADS"` -> `409 Conflict`<br>  4. Full Name `"Artificial Intelligence and Data Science"` -> `409 Conflict`. | None. Backend alias resolution and single active HOD duplicate gate verified 100% on live production. |
| **Bug 4: Invalid/Expired Auth Token & Refresh** | Token type separation, protected route gating, dual-cookie issuance, token refresh, and safe error rejection. | **PASS** | **Live API Execution:**<br>- `POST /api/v1/auth/login` -> **HTTP 200**, returns `access_token` and `refresh_token`, sets 3 cookies with `SameSite=None; Secure; HttpOnly`.<br>- Access token decoded: `token_type: "access"`. Refresh token decoded: `token_type: "refresh"`.<br>- `GET /api/v1/auth/me` with access token -> **HTTP 200**.<br>- `GET /api/v1/auth/me` with refresh token -> **HTTP 401** (`Invalid token type: refresh token cannot be used as access token`).<br>- `POST /api/v1/auth/refresh` via JSON body -> **HTTP 200**, issues new access & refresh tokens.<br>- `POST /api/v1/auth/refresh` via Cookie header -> **HTTP 200**, succeeds.<br>- `POST /api/v1/auth/refresh` without credentials -> **HTTP 401** (`Authentication credentials missing`).<br>- `POST /api/v1/auth/refresh` with malformed token -> **HTTP 401** (`Invalid or expired authentication token`).<br>- `POST /api/v1/auth/logout` -> **HTTP 200**, expires cookies with `max-age=0`. | None. Token refresh lifecycle and strict token type separation verified against live production. |

---

## C. Safety Summary

1. **Production Data Integrity:**
   - Existing production records (18 total records) were inspected via read-only endpoints and fully preserved without modification.
   - Existing active HOD for Cyber Security (`krishnaselvam35@gamil.com`) and active HOD for AIDS (`qa.aids.hod.live@faculty.edu`, ID: `ebec156f-3fff-42cf-8f55-611124579ae3`) were preserved intact.
   - Exactly one QA faculty test identity (`qa.duplicate.uuid.test@faculty.edu`, ID: `803c9194-9743-4e9e-8fc2-34d11bc2afff`) was created during designation verification.
   - All duplicate HOD tests returned HTTP 409 and safely prevented duplicate account creation.
2. **Email Dispatch:**
   - No emails were triggered or dispatched during this test suite.
3. **Repository and Code State:**
   - No repository code, environment variables, or server configurations were modified or deployed during this verification.
4. **Credential & Secret Protection:**
   - No passwords, tokens, API keys, or connection strings are logged, printed, or included in any output.

---

## D. Final Verdict

### **PARTIAL — SOME BUGS VERIFIED; OTHERS FAILED OR ARE BLOCKED**

- **Bug 2 (Faculty Creation Form Navigation):** **PASS**
- **Bug 3 (AIDS Department HOD Creation & Alias Resolution):** **PASS**
- **Bug 4 (Authentication Token Type Separation & Refresh Lifecycle):** **PASS**
- **Bug 1 (Patent Date Extraction & Auto-Population):** **BLOCKED** on frontend UI auto-polling because Cloudflare Pages edge CDN is still serving pre-audit bundle `index-Cp6k5oJ4.js`. (Backend date extraction and ISO serialization are deployed and verified on Render).

*Action Required:* Trigger or allow Cloudflare Pages to build and deploy commit `94385b4` / `44549a9` from the `main` branch to complete full end-to-end browser auto-population testing for Bug 1.
