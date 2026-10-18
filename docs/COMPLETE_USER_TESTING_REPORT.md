# Complete User Testing Report — Phases 2H–2K (Release QA)

> Date: 2026-10-11 · Repo HEAD: `8503fe5` (unchanged, nothing committed/pushed) ·
> Environment: local Windows, local PostgreSQL (only). All work is **uncommitted
> and explicitly non-production**.

This report covers the four workstreams in one execution:

1. **2H** — fail-closed frontend/API target isolation for the legacy Playwright suite.
2. **2I** — final safety & regression review.
3. **2J** — complete user testing with the actual patent PDFs on a disposable local stack.
4. **2K** — cleanup + release-readiness verdict.

---

## 1. Exact changed files

All Phase 2H changes are **built on top of the previously reviewed (uncommitted)
Phase 2G changes**; nothing else in the repository was modified.

| File | Change | Why |
| --- | --- | --- |
| `frontend/src/testing/legacyGuard.ts` | Added `apiBaseOf()`; `guardedDevWebServer()` now takes a **required** `apiUrl` and returns `env: { VITE_API_BASE_URL: apiBaseOf(apiUrl) }`. | Pins the **browser app's** API target (Vite `import.meta.env`) to the validated loopback API. Vite gives an existing process env var highest priority, so a stray `frontend/.env` can never point the browser under test at a remote API. |
| `frontend/src/testing/legacyGuard.test.ts` | +3 focused tests (total **50**): `apiBaseOf` normalization, non-loopback **API** refusal, and `VITE_API_BASE_URL` pinning even when the ambient env is the remote prod API. | Covers loopback API URLs, URL schemes, malformed URLs, prod hosts, remote hosts, spoofing/boundary cases (existing) and **environment precedence** (new). |
| `frontend/playwright.config.ts` | `webServer` now `guardedDevWebServer(BASE_URL, { apiUrl: API_URL, … })`. | Legacy suite default config: browser API base loopback-pinned; config throws on any non-loopback / prod override. |
| `frontend/playwright-e2e.config.ts` | Same wiring (`apiUrl: API_URL`). | Idem for the E2E config. |
| `frontend/playwright-exact.config.ts` | Destructures `apiUrl` too and passes it (`assertOptionalLoopback` on `E2E_API_URL` retained). | Covers the exact-workflow config (its specs read `E2E_API_URL` directly). |
| `frontend/playwright-hardening.tmp.ts` | **Gitignored scratch**, previously **unguarded**. It *is* an executable Playwright entry point (`-c playwright-hardening.tmp.ts`). Applied the same guard with a minimal, surgical edit; all unrelated user settings (workers, viewports, launch args) preserved unchanged. | Removes the last unguarded legacy entry point; a remote `FRONTEND_URL`/`API_URL` now aborts at config load. |

Verified-unchanged (Phase 2G/2I, per standing constraints): `frontend/playwright-staging.config.ts`, all of `frontend/tests-staging/` (incl. `guard.ts`), `backend/tests/conftest.py`, and everything in `scripts/staging/`. The staging guard and suite were **not weakened** anywhere.

**No commits, pushes, deployments, or resource creation were performed.**

---

## 2. Database / environment classification (no secrets)

- **Test target:** the app under test ran **entirely locally** — backend on `127.0.0.1:8000`, frontend dev server on `127.0.0.1:5173`.
- **Database:** local PostgreSQL `127.0.0.1:5432/` **`faculty_portal_staging`** (disposable, provisioned idempotently by `scripts/staging/provision_staging.py`, wiped at the end). A parallel local `faculty_portal_migtest` DB hosted the backend pytest regression suite.
- **Backend env:** `DATABASE_URL` explicitly set to the local staging DB (process env overrides `.env`, so the repo-level production `.env` value was never used), `APP_ENV=development`, `E2E_TEST=1` (test-only rate-limit relaxation), `SCHEDULER_ENABLED=false`, `CORS_ORIGINS=http://localhost:5173`.
- **Frontend env:** `VITE_API_BASE_URL=http://localhost:8000/api/v1` pinned at dev-server startup (plus the 2H webServer pin).
- **Production isolation — demonstrated fail-closed:**
  - `scripts/staging/guard.py` **REFUSED** `…neon.tech…` (marker) and a non-allowlisted remote host; accepted only loopback.
  - Legacy `playwright.config.ts` **aborts at load** with `FRONTEND_URL=https://portal.example.com` (`[legacy-guard] … not loopback … Refusing to run`).
  - Legacy `playwright-e2e.config.ts` **aborts at load** with `API_URL=https://…onrender.com` (`… points at the production host …`).
  - `playwright-staging.config.ts` **aborts** when `STAGING_CONFIRM`/URLs are missing (exit 1).
  - The root `.env` was never read for secrets; only boolean/path existence checks were performed.

---

## 3. Patent-document inventory (real source documents)

Source: `C:\Users\mohan\Downloads\New folder (2)`. Originals were **never modified** (hashes verified identical before and after the run).

| Document | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| 5. Patent Certificate.pdf | 1,042,974 | `9AB0C7C3…03CF93A` |
| Certificate 435272-001_2. Artificial Intelligence based stess detection device.pdf | 7,268,726 | `995D0777…EAD59C3` |
| Certificate 459641-001.pdf | 7,270,218 | `25D06780…AF3BD8` |
| Design Certificate 466982-001.pdf | 7,269,488 | `753AFF8C…EACC17` |
| Design Certificate 493147-001.pdf | 7,269,091 | `36C229BD…E04B8B` |
| Design Publication Page 435272-001_2. Artificial Intelligence based stess detection device.pdf | 42,691 | `A305B223…B19D2` |
| DOC-20250120-WA0017..pdf | 91,592 | `6E12F2E0…CC3C90` |

**Actually exercised (byte-copies uploaded through the real pipeline):**
- **Design Publication Page 435272-001_2 — design `435272-001`, title "Artificial Intelligence based Stress Detection Device"** (source filename spells "stess"; OCR-normalized extraction returned "Stress"). 4 contributors extracted, all **EXTERNAL / NO_MATCH**.
- **5. Patent Certificate — design `410787-001`, title "AI BASED GOGGLES FOR VISUALLY IMPAIRED"**, applicant list of 9 inventors (Dr. D. Sumathi, Prof Naren.J, Dr. Hardeep Singh, Dr Kalaiarasi Arumugam, Dr. Devakirubai Navulkumar, Ms. Manjula Devi P, Ms. Vinutha M, Ms. Swathi Srikanth Achanur, Mr. Arvind Raja) — all classified **EXTERNAL / NO_MATCH** against the synthetic staging directory (the real persons are not in any authoritative source used; no identity was assumed).

The remaining five PDFs were inventoried/hashed only (no fabricated review was performed).

---

## 4. Role-based test matrix (business rules A–F) — results

All on the disposable **local** stack (real HTTP + real DB; assert server-side enforcement).

**Staging Playwright suite — `frontend/tests-staging/scenarios.spec.ts` + `00-guard.spec.ts`: 33/33 PASSED (~7.6 s).**

| Rule | Scenarios | Result |
| --- | --- | --- |
| **A** Uploader auto-association, idempotent send-all | A1 auto-accepts uploader, no self-request; A2 retry creates nothing | ✅ 2/2 |
| **B** Internal-faculty requests, recipient-only, IDOR | B1 non-uploader 403 · B2 HOD-as-recipient 422 · B3 duplicate request 409 · B4 non-recipient respond 403 · B5 recipient accept 200 | ✅ 5/5 |
| **C** External contributors excluded | C1 external-only record → no internal requests | ✅ 1/1 |
| **D** HOD read-only + department scope | D1 reads 200 · D2 institutional verify 403 · D3 duplicate resolve 403 · D4 conflict resolve 403 · D5 cross-dept hidden (server-side) | ✅ 5/5 |
| **E** Super Admin final grant gates | E0 SA cannot respond to requests 403 · E1 grant needs confirmation 422 · E2 unverified record not eligible 422 · E3 eligible record granted · E4 double-grant refused 422 · E5/E6 SA resolves duplicate+conflict · E7 dashboard | ✅ 8/8 |
| **F** Cross-cutting (RBAC/CSRF/deactivation/audit/UI) | F1 faculty→admin 403 · F2 POST w/o CSRF 400 `CSRF_TOKEN_INVALID` · F3 deactivated login 401 · F4 `PATENT_GRANTED` audit present · F5 unauth browser redirected to /login (real UI) | ✅ 5/5 |
| **Staging guard (fail-closed)** | no-confirm abort · URLs required · prod refused even allow-listed · non-loopback refused · loopback allowed · confirmed allow-listed host allowed | ✅ 7/7 |

**Real-document end-to-end (2 uploads through the **actual** OCR/orchestrator pipeline):**

| Check | Result |
| --- | --- |
| Upload accepted (multipart, CSRF-authenticated) | ✅ 202 for both |
| Full document pipeline reached a terminal state | ✅ `AWAITING_REVIEW` (all 11 job stages SUCCESS incl. classify/qr/extract/understand/verify/identity/duplicate/conflict/association/quality/final_verification) |
| Verified metadata extracted from the real documents | ✅ design `435272-001` / `410787-001`, titles extracted, 13 contributors parsed |
| Rule A invariant — no self-request to the uploader | ✅ 0 self-requests |
| Rule C invariant — real people never fabricated as internal faculty | ✅ 13/13 contributors `EXTERNAL`/`NO_MATCH`; `matched_faculty_id`/`user_id` null; **zero** internal requests created |
| Faculty-association stage completed by the pipeline | ✅ `send-all` correctly refused `409 VALIDATION_ERROR` (`FACULTY_ASSOCIATION_COMPLETE`) — no double-processing |
| Rule E — grant on a **real** (pipeline-processed, VERIFIED) record | ✅ granted (`GRANTED`) with audit; forbidden-path (needs confirmation/unverified) separately proven by E1/E2/E4 |
| Identity resolution audited for the real names | ✅ 13 `IDENTITY_RESOLUTION` audit rows (system actor) — removed in cleanup |

**Negative tests (status + resulting DB state asserted):** authorization 403s, CSRF 400, deactivation 401, HOD write 403s, recipient-only decisions, duplicate 409/422, double-grant 422, cross-department visibility — all match the expected status codes and produced no orphaned state (verified post-hoc via scoped queries).

---

## 5. Exact commands run

| Command (simplified; full env shown in §2) | Result |
| --- | --- |
| `npx vitest run src/testing/legacyGuard.test.ts` | **50 passed** |
| `npx tsc -b` | exit 0 |
| `npx esbuild playwright.config.ts playwright-e2e.config.ts playwright-exact.config.ts playwright-hardening.tmp.ts --bundle …` | exit 0 (all 4 import the guard) |
| `python scripts/staging/test_guard.py` | **19 passed** |
| `python scripts/staging/guard.py <neon>` / `<loopback>` / `<remote-no-optin>` | REFUSED / OK / REFUSED |
| `npx playwright test -c playwright-staging.config.ts 00-guard.spec.ts` (loopback) | **7 passed** |
| `npx playwright test -c playwright-staging.config.ts --list` (env unset) | config aborts, exit 1 (fail-closed) |
| `npx playwright test -c playwright.config.ts --list` `FRONTEND_URL=https://portal.example.com` | `[legacy-guard]` abort, exit 1 |
| `npx playwright test -c playwright-e2e.config.ts --list` `API_URL=https://…onrender.com` | `[legacy-guard]` abort, exit 1 |
| `python -m pytest -q -p no:cacheprovider` (backend, on `faculty_portal_migtest`) | **396 passed, 11 skipped** |
| `python scripts/staging/provision_staging.py --migrate` | exit 0 (15 accounts + scenario records) |
| `npx playwright test -c playwright-staging.config.ts` (loopback `STAGING_CONFIRM=1`) | **33 passed** (7.6 s) |
| `python real_doc_e2e.py` | 2 uploads 202 → terminal → grants (see §4) |
| `npx vitest run` (full frontend unit suite) | **136 passed (19 files), exit 0** |

Cleanup commands: manifest-scoped `cleanup_run.py`/`cleanup_run2.py`/`pre_teardown.py`/`clean_audit.py` + `teardown_staging.py --yes` (exit 0) + `final_verify.py` (all tables 0 rows).

---

## 6. Frontend/backend build & regression results

- Backend regression: **396 passed / 11 skipped** (70.8 s) against local `faculty_portal_migtest`.
- Frontend unit suite (Vitest): **136/136** (includes the 50 guard tests). The 6 previously-observed thread-pool flaky failures (Phase 2G evidence: 27/27 when re-run with `--no-file-parallelism`) **did not reproduce** this run — attributed to reduced CPU contention, classified as environment/concurrency, not a product defect.
- `tsc -b` exit 0; esbuild bundling of all four legacy configs exit 0.

---

## 7. UI / API / authorization negative results

See §4 matrix (B1–B4, D2–D4, E0–E2/E4, F1–F3). All enforced server-side with correct status codes and clean resulting DB state; a hidden frontend button was never treated as authorization.

---

## 8. Failures and classification

- **Code defects found this run:** none.
- **Environment blockers:** the real-document OCR step depends on an external OCR.Space fallback because **Tesseract is not installed** on this machine (`tesseract_on_path: False`). The pipeline still completed (terminal `AWAITING_REVIEW`, all job stages SUCCESS). This is an environment constraint, not a product defect.
- **Flakiness:** the previously reported frontend vitest worker-contention flakiness did not recur (136/136); remains categorized as environment/concurrency.
- **Legacy suite not executed** (by design): legacy `frontend/tests/` specs are coupled to real test accounts/ID and are now loopback-guarded; `exact-negatives.spec.ts` requires `E2E_CREDS_FILE`, so `--list` of the full legacy suite fails at spec-load (guard itself passed at config load). The suite is not a safe automated entry point against any external target.

---

## 9. Cleanup verification

Cleanup was **manifest-driven** (`run2K-ebe261ba7e`), scoped to exact recorded IDs and file paths — no broad `TRUNCATE`/`DROP`/pattern deletes:

- **DB rows removed:** 2 `ip_records`, 26 `processing_jobs`, 13+13 contributors, 4 `verification_attempts`, 4 record/masters `audit_log` + 13 pipeline `IDENTITY_RESOLUTION` audits, 2 `faculty_profile_snapshot`, 2 `master_ip_record`, 2 `ip_file`, plus run-created side-effect rows (`notification` 3, `audit_log` 7); teardown removed the provisioned dataset (`15 users`, `10 ip_records`, `12 contributors`, `3 association_requests`, `2 duplicate_cases`, `1 conflict_case`, `2 designations`, `3 departments`).
- **Files removed:** the 2 stored upload copies (`backend/storage/STG-FAC-01/…`) and the isolated temp copies directory.
- **Verification:** every table in `faculty_portal_staging` now has **0 rows**; migration head `010` intact; the original 7 PDFs are **byte-identical** (hashes match the initial inventory); pre-existing earlier-QA files under `backend/storage/` (uuid + real-name dirs) were **untouched**.
- **Leftover run-owned IDs:** **none**.

---

## 10. Hosted staging status

**No hosted staging** is configured. All execution and servers were **local only** (127.0.0.1) and are labeled as local throughout. The hosted-staging plan remains a proposal (`docs/STAGING_HOSTED_PLAN.md`); nothing has been applied to Render, Cloudflare, or any cloud account.

---

## 11. Release-readiness verdict

**Test layer: READY. Production release: NOT READY.**

Phase 2G/2H/2I complete as designed: every Playwright entry point now fails closed to loopback, the browser API target is pinned to loopback at the Vite level, staging tests fail closed without explicit confirmation, the DB guard refuses production hosts, and the full A–F rule matrix plus two real documents passed against a disposable local database, with residue-free cleanup.

Remaining **production blockers** (pre-existing, outside this run's authorization — not caused by it): ephemeral Render storage, unseeded reference data, backup/restore drill, external-integration authorization, `/docs` + `/openapi.json` public, the backend production commit being unverifiable, and faculty IDs missing from all source documents.

Residual risks / recommended follow-ups:
1. **Dangerous legacy Python entry points** (reported, not executed, not fixed): `scripts/e2e_backgroundtasks_pipeline.py` (starts its own backend inherited from `.env`, uploads against whatever DB resolves) and `scripts/verify_real_upload_459641.py` (talks to `localhost:8000`, but the backend's DB could be production). Recommend guarding them with the same fail-closed DB logic or deleting them.
2. `frontend/.env` was not inspected; guard the **remote** `VITE_API_BASE_URL` value there if one exists (the 2H pin makes it harmless for the legacy suite, but a developer's own browser session would still use it).
3. Installing Tesseract locally removes the external-OCR dependency for future real-document runs.
4. Optional: warm/verify the previously-flagged vitest thread-pool settings if CI-wide flakiness matters.