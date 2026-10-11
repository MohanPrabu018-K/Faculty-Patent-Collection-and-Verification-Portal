# Engineering Audit — Faculty Patent Collection & Verification Portal

Date: 2026-10-11
Scope: read-only audit of the repo at `E:\Faculty profile portal` plus a small set of
verified, reversible fixes. No commits, pushes, deploys, or production/database
mutations were performed.

> **Reporting note.** No production endpoint, verification provider (IP India / InPASS)
> or OCR.Space call was validated, because doing so requires a live, authenticated
> production session (and would risk prod data). Those paths are marked
> **Not validated** below rather than assumed to work.

---

## 1. Executive summary

The application is well-built in the areas that matter most: the Super-Admin-only
grant flow is enforced server-side with row locking and explicit gates, faculty/HOD
IDOR is prevented by ownership + department checks, association responses are
recipient-only with deactivated-user blocking, and upload validation checks
extension + magic bytes + size + dimensions. The frontend builds cleanly and its
86 unit tests pass deterministically.

However, the **database provisioning path was broken**: a database built from the
committed Alembic migrations could not be created at all, and even once created it
was missing a column the ORM selects on every query. Production happened to work
only because its schema was modified out-of-band. In addition, the **test suite
defaulted to the production database**, so a routine `pytest` run created and
deleted rows in production.

Across two audit passes the confirmed defects were fixed and verified. The final
backend suite is **`396 passed, 11 skipped, 0 failed` (exit 0)** and the frontend is
**18 files / 86 tests passed** plus a clean production build. The previously-failing
five tests were traced to **test-fixture defects** (missing reference-data seeding, a
department-visibility precondition, one non-hermetic test) and repaired with
deterministic fixtures — none were relabelled "environmental" without proof.

The second pass (2026-10-11) additionally hardened the **association/HOD workflow**
against the authoritative business rules (A–F, §3A): the uploader is auto-associated
server-side; only the uploader may dispatch association requests; HODs are strictly
**read-only** for institutional verification and duplicate/conflict resolution (those
capabilities now live with the Super Admin only); and every rule is enforced in the
backend with new regression tests that exercise the *APIs directly*, not the UI.

---

## 2. Baseline & environment (verbatim evidence)

| Item | Value |
| --- | --- |
| Branch / HEAD | `main` @ `aca01b9` |
| Frontend | React 19.2.8, TypeScript 7.0.2, Vite 8.2.2, Vitest 5.0.1, Playwright 1.62.1 |
| Backend | FastAPI 0.141.1, SQLAlchemy 2.0.52, Alembic 1.19.2 (asyncpg + psycopg2) |
| Python | 3.12.10 (`backend/.venv`) |
| DB target in root `.env` | **PRODUCTION Neon** (host deliberately redacted here — never publish it), while `APP_ENV=development` |
| Local DB used for verification | `127.0.0.1:5432`, disposable database `faculty_portal_migtest` |

**Baseline before fixes**

- `alembic upgrade head` on a **fresh** database **failed at migration 008**.
- `pytest tests --collect-only` → 401 tests collected.
- Full backend suite against a migrated local DB → `350 passed, 5 failed, 43 errors`.
- `npm test` (bare `vitest run`) picked up the Playwright `tests/*.spec.ts` files and
  used the flaky default `forks` pool.
- `npm run build` → passed.

**After fixes**

- `alembic upgrade head` on a fresh DB → **succeeds to `010`**; zero model/schema drift.
- Full backend suite → **`396 passed, 11 skipped, 0 failed, 0 errors`** (exit 0, ~174s).
- `npm test` → **18 files / 86 tests passed**, deterministic (≈7s).
- `npm run build` → passed (`tsc -b` clean, exit 0).
- `pytest` now **refuses** to run against a non-local DB unless explicitly overridden.
- `alembic current` = `alembic heads` = `010 (head)` — single head, no split.

---

## 3. Findings

Severity: **P0** critical (security/data-loss/unsafe) · **P1** high · **P2** medium · **P3** low.

### P1 — Fresh-database migrations could not run (FIXED)
`001_initial_schema.py` creates `user_role_enum` with only `('super_admin','faculty')`,
but `app/models/base.py` (`USER_ROLE_CHOICES`) and migration
`008_single_active_hod_per_department.py` use `'hod_admin'`. No migration ever added the
value, so `008`'s partial index
(`WHERE role = 'hod_admin'`) failed on a fresh DB with
`invalid input value for enum user_role_enum: "hod_admin"`. Production only worked
because the type was altered out-of-band (no committed migration does this; the
in-repo `backend/update_enum.py` is not the cause — it alters
`processing_status_enum`, not `user_role_enum`).

*Fix:* new `007a_add_hod_admin_to_user_role.py` (`ALTER TYPE ... ADD VALUE IF NOT EXISTS
'hod_admin'`, idempotent/additive); `008.down_revision` re-pointed to `007a`. Verified.

### P1 — Migration schema drift: `ip_record.is_archived` missing (FIXED)
`app/models/base.py:221` defines `is_archived = Column(Boolean, default=False,
nullable=False, index=True)` and it is selected/updated throughout
(`app/api/admin.py:849,953-967`, `app/services/search_analytics.py:460`). No migration
created it, so **every `SELECT` of an `IpRecord` failed** on a migrated DB with
`column ip_record.is_archived does not exist`. A model↔schema diff found this was the
**only** missing column across 23 model tables.

*Fix:* new `010_add_ip_record_is_archived.py` (adds
`NOT NULL BOOLEAN DEFAULT false` + `ix_ip_record_is_archived`). It is written
**idempotently** (`IF NOT EXISTS`) because production already has the column
out-of-band via `backend/migrate_add_is_archived.py`; see §9.1. Verified: drift = 0.

### P1 — Tests default to the production database (GUARDED)
Root `.env` sets `DATABASE_URL` to production while `APP_ENV=development`, so the
README's own instruction (`cd backend && python -m pytest tests`) wrote `gv-`/`tg-`
rows to production. The only guard (`app/core/config.py:190-199`) applies solely to
`APP_ENV` in prod envs.

*Fix:* `backend/tests/conftest.py` aborts the run if the resolved `DATABASE_URL` host
is non-local, unless `ALLOW_REMOTE_TEST_DB=1` is set deliberately. Verified: local →
runs; remote → exits with a clear message; remote + override → runs. **Recommend also
updating the README "Tests" section** to document the local-DB requirement.

### P1 — No reference-data seeding; documented setup is broken
`scripts/setup_dev.sh:43` runs `alembic seed` ("Seeded super admin + departments"), but
**no `seed` command or seed script exists anywhere**. `README.md:78` also notes the E2E
script "needs ... seeded users". Reference data (super admin, departments, the `"HOD"`
designation) exists only in production via manual creation. Tests such as
`test_admin_governance.py:142` explicitly fail with `"HOD designation seed required"`.

*Recommended:* add an idempotent seed script (designations, departments, super-admin from
env) and wire it to `alembic seed` (or fix `setup_dev.sh`). *Not implemented* — the
institution-specific taxonomy (department/designation names) requires product input.

### P2 — Test suite not isolated: `SchedulerAlreadyRunningError` (FIXED)
`app/services/scheduler.py` uses a process-wide `AsyncIOScheduler` singleton;
consecutive app lifespans in one process (one `TestClient` per test module) called
`start()` again, raising `apscheduler.schedulers.SchedulerAlreadyRunningError: Scheduler
is already running` — **43 errors** in the full suite.

*Fix:* made the lifespan idempotent (`if not _scheduler.running: start()`; shutdown only
when running). Production behaviour is unchanged (single lifespan per process); suite
errors 43 → 0.

### P2 — Frontend test command unreliable (FIXED)
`frontend` had no `test` block, so bare `vitest run` collected the Playwright specs in
`tests/` and used the flaky default `forks` pool.

*Fix:* `frontend/vitest.config.ts` scopes to `src/**/*.{test,spec}.{ts,tsx}`, excludes
`tests/**`, and uses `pool: 'threads'`. Result: deterministic 18 files / 86 tests.

### P2 — Stale test fixture masked a real grant gate (FIXED)
`tests/test_grant_csrf.py` created a "verified" `IpRecord` with `workflow_state=VERIFIED`
but no `processing_status` (model default `PENDING`). The (intentional) grant gate
`app/api/admin.py:1053` requires `processing_status in (COMPLETED, COMPLETED_WITH_ERRORS,
AWAITING_REVIEW)` → 422 `GRANT_PROCESSING_INCOMPLETE`.

*Fix:* fixture now sets `processing_status="COMPLETED"`. All 6 tests in the file pass.

### P2 — Auth: refresh token has no rotation/revocation
`app/api/auth.py:302-367` decodes the refresh cookie and mints a new access token with
the same `jti`; there is no rotation, blacklist, or one-time use. A stolen refresh token
can be reused until expiry. Sessions can't be revoked server-side.
**Theory, not exercised.** *Recommended:* rotate + persist/verify `jti` on refresh.

### P2 — Upload: dimension validation is fail-open
`app/api/uploads.py` (~326-342) swallows parser errors when checking PDF page count /
image dimensions (`except ...: pass`), so an unparseable file bypasses the size/page
limit at the upload gate. *Recommended:* fail closed (reject) or mark for review.

### P2 — Frontend: resilience, error surfacing, and a11y
- Tokens kept in module singletons (`src/api/client.ts:129-130`); `api.refresh` /
  `useAuth().refresh` are never called → every 401 has no recovery path.
- Raw backend payloads rendered to users (`String(error)`) in
  `AdminDashboardPage`, `RecordsPage:76`, `RecordDetailPage:131,328`, etc.
- Silent mutation failures: `NotificationsPage.tsx:29-33`, `NotificationBell.tsx:27-45`.
- Query invalidation gaps after mutations (`AdminFacultyPage.tsx:57`,
  `AdminGrantedPatentsPage.tsx:35-36`, `AdminQueuesPage.tsx:72`).
- Accessibility: `components/ui.tsx:78-96` Modal has no focus trap/restore/initial
  focus; a custom overlay modal in `AdminGrantedPatentsPage.tsx:117-129` has no dialog
  semantics; clickable `<tr onClick>` (`AdminRecordsPage.tsx:217`) and notification
  dropdown items (`NotificationBell.tsx:87`) are not keyboard-accessible.

### P2 — Architecture: oversized/duplicated modules
`src/features/hod/HodPages.tsx` is 571 lines (7 pages + helpers); shared "Refresh
failed… Retry" banners and local `display()` helpers are duplicated across ~10 files;
dead code (`ConflictDetailModal`, `useDebouncedValue`). See §6 for the top refactors.

### P3 — Pre-existing migration downgrade bug
`backend/alembic/versions/005_...py:63` calls `op.drop_constraint(None, ...)`, which
cannot compile (unnamed FK). `alembic downgrade` below `005` fails. Forward upgrades are
unaffected. *Recommended:* name the constraint or drop it via `information_schema`.

### P3 — Smaller items
- `README.md` references React 18; actual stack is React 19.
- `frontend/tsconfig.json` enables `strict` but not `noUnusedLocals`,
  `noUnusedParameters`, `noUncheckedIndexedAccess`; no ESLint/lint script exists.
- `src/api/ui.tsx:43-46` classifies errors with `/\b0\b/`, which can misfire.
- `src/api/client.ts:115` `decodeURIComponent` can throw on a malformed cookie.
- Test hermeticity: some fixtures use deterministic ids (e.g. `FAC-GV-GV-ADM`) rather
  than per-run UUIDs, so an interrupted run leaves collisions.
- **Not validated in this audit (no live access provided):** the 11-agent OCR
  pipeline end-to-end, IP India / InPASS verification, OCR.Space integration, SMTP
  password-reset email delivery, and Playwright browser E2E.

---

## 3A. Workflow & authorization verification (rules A–F, verified 2026-10-11)

Verified by reading the backend endpoints and by regression tests that call the APIs
directly (a hidden UI control is **not** treated as an authorization boundary).

| Rule | Requirement | Enforcement point | Verdict |
| --- | --- | --- | --- |
| **A** | Uploader auto-associated server-side; no acceptance step; no dup/loss on retries | Upload associates the uploader automatically; `POST /associations/` rejects the uploader as a recipient | ✅ Holds |
| **B** | Other internal faculty get explicit requests; recipient-only decisions; authz/ownership/status/dup/audit enforced | `POST /associations/` (uploader-only dispatch), `{id}/respond` (recipient-only; HOD responder blocked) | ✅ Holds |
| **C** | Externals excluded from internal faculty/HOD/identity flows; data preserved | `_other_internal_reviewers` excludes externals/inactive/HOD; no invented external workflow | ✅ Holds |
| **D** | HOD strictly **read-only** for association decisions, institutional verification, duplicate/conflict resolution; dept scope server-side | `verification.py` institutional verify → `super_admin` only; `duplicates.py::_assert_can_act_on_case` and `conflicts.py` resolve → `super_admin` only; HOD GETs remain department-scoped read-only | ✅ Holds |
| **E** | Super Admin has **no** association Accept/Reject; retains only final Grant, fully gated | No SA association decision endpoints; `POST /admin/ip-records/{id}/grant` gated (§5) | ✅ Holds |
| **F** | All rules backend-enforced; IDOR/privilege-escalation/invalid-transition/cross-dept/dup prevented | Ownership + dept checks, state machine, row lock, single-HOD DB index | ✅ Holds |

**Changes made to satisfy rules B/D/E (all uncommitted, see §4):**

- `POST /api/v1/associations/` now returns **404** for a missing record, **403** unless the
  caller is the uploader (or a Super Admin), and **422** when an HOD is named as a recipient.
- `POST /api/v1/associations/{id}/respond` blocks HOD responders (**403**).
- Legacy `POST /api/v1/faculty/{record_id}/associate/{other_faculty_id}` received the same
  uploader-only + HOD-recipient hardening.
- Institutional verification (`POST /api/v1/verification/institutional/{record_id}`) is now
  **Super-Admin-only**; the HOD branch was removed (HOD keeps the read-only dept-scoped GET).
- Duplicate/conflict resolution (`POST /api/v1/duplicates/{id}/resolve`,
  `POST /api/v1/conflicts/{id}/resolve`) is now **Super-Admin-only**.
- Frontend: HOD Duplicates/Conflicts pages are read-only (action buttons removed;
  `resolveDuplicate`/`resolveConflict` wrappers removed from `client.ts`). The Super Admin
  retains resolution via `AdminQueuesPage`.

**Regression tests added/extended:** `test_association_lifecycle.py` (uploader-only dispatch,
HOD-recipient 422, HOD-respond 403), `test_hod_manual_verification.py::test_hod_cannot_verify_readonly`,
`test_staged_workflow.py::test_admin_verify_blocked_with_exact_counts`, and
`test_batch12_fixes.py::TestHodReadOnlyResolutionDenied` (HOD resolve → 403 on both endpoints,
state unchanged, Super Admin → 200).

---

## 4. Fixes implemented (all verified, reversible)

| # | File | Change |
| --- | --- | --- |
| 1 | `backend/alembic/versions/007a_add_hod_admin_to_user_role.py` (new) | Add `hod_admin` to `user_role_enum` (idempotent) |
| 2 | `backend/alembic/versions/008_single_active_hod_per_department.py` | `down_revision` → `007a` |
| 3 | `backend/alembic/versions/010_add_ip_record_is_archived.py` (new) | Add `ip_record.is_archived` + index — **idempotent** (`IF NOT EXISTS`); see §9 |
| 4 | `backend/tests/conftest.py` (new) | Refuse to run tests against a non-local DB |
| 5 | `backend/app/services/scheduler.py` | Idempotent scheduler start/shutdown |
| 6 | `backend/tests/test_grant_csrf.py` | Fixture sets `processing_status="COMPLETED"` |
| 7 | `frontend/vitest.config.ts` (new) | Scope tests to `src`, use `threads` pool |
| 8 | `backend/app/api/associations.py` | Uploader-only dispatch (403), HOD-recipient block (422), HOD-respond guard (403) |
| 9 | `backend/app/api/faculty.py` | Same uploader-only + HOD-recipient hardening on the legacy associate route |
| 10 | `backend/app/api/verification.py` | Institutional verify → `super_admin` only (HOD dept branch removed) |
| 11 | `backend/app/api/duplicates.py` / `conflicts.py` | Resolve → `super_admin` only (Rule D) |
| 12 | `frontend/src/features/hod/HodPages.tsx` | HOD Duplicates/Conflicts made read-only |
| 13 | `frontend/src/api/client.ts` | Removed HOD `resolveDuplicate`/`resolveConflict` wrappers |
| 14 | `backend/tests/{test_admin_governance,test_batch12_fixes,test_hardening}.py` | Deterministic fixtures replace the 5 failing environment-dependent tests |
| 15 | `backend/pytest.ini` (new) | `testpaths=tests`, `asyncio_mode=auto` so documented `pytest` is hermetic |

Migration chain after fixes: `001 → 002 → 003 → 52ce3b033131 → 005 → 006 →
f5cfdeecb51b → 007 → 007a → 008 → 009 → 010` (head).

---

## 5. Previously-failing tests — root cause and fix (now GREEN)

The baseline suite against a migrated local DB showed `350 passed, 5 failed, 43 errors`;
after fixes it is `396 passed, 11 skipped, 0 failed, 0 errors`. Each of the five failures
was diagnosed and fixed at the fixture level (assertions were **not** weakened):

| Test | Root cause | Fix |
| --- | --- | --- |
| `test_admin_governance.py::TestHodUniqueness` ×3 | No `"HOD"` `Designation` row exists on a freshly-migrated DB; admin code keys "is this a HOD?" off `Designation.title.upper() == "HOD"` | Module-scoped autouse `_hod_designation` fixture creates it idempotently and removes it afterwards **only if it created it** |
| `test_batch12_fixes.py::TestDisplayNamesEnriched` | Records were seeded in `VERIFICATION_REQUIRED`, which HOD documents-visibility (Rule D) hides; the name assertion got zero rows (`StopIteration`) | Seed the records at `FACULTY_ASSOCIATION_COMPLETE` (past the faculty stage, as the endpoint requires); test now also covers the admin-queue display path |
| `test_hardening.py::test_processing_job_agent_trail_per_record` | Non-hermetic: scanned arbitrary pre-existing admin records for an 11+ step trail — always empty on a fresh DB | Rewritten to seed a dedicated record + the 11 real agent `ProcessingJob` rows (`classify, qr, extract, understand, verify, identity, duplicate, conflict, association, quality, final_verification`), assert `GET /uploads/{id}/status` returns the full set, then delete the record + jobs in a `finally` block |

The `43 errors` were `SchedulerAlreadyRunningError` from repeated app lifespans (§3, P2),
fixed by the idempotent scheduler. No remaining backend test failures exist.

---

## 6. Recommended next steps (priority order)

1. **Add the seed script** and fix `setup_dev.sh` / README (unblocks fresh deploys,
   tests, and onboarding). — highest operational value.
2. **Refresh-token rotation/revocation** in `auth.py` (P2 security).
3. **Fail-closed upload dimension validation** (P2).
4. **Frontend data layer**: single typed error mapper, 401/token-refresh interceptor,
   query-key factory, remove `as any`/duplicated `display()`; split `HodPages.tsx`.
5. **Accessibility**: focus-trapped shared `Modal`, keyboard-accessible table rows and
   dropdown items.
6. **Fix the `005` downgrade** and add `noUnusedLocals` + ESLint.
7. **Update README** (React 19, local-DB testing, real seed step).

---

## 7. How to reproduce the verification

```powershell
# --- from repo root, using the backend venv ---
$env:DATABASE_URL='postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/faculty_portal_migtest'
.\backend\.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head   # fresh DB -> 010
.\backend\.venv\Scripts\python.exe -m alembic -c alembic.ini current        # 010 (head)
.\backend\.venv\Scripts\python.exe -m alembic -c alembic.ini heads          # 010 (head)

# --- backend suite (local DB only) ---
cd backend
python -m pytest -q -p no:cacheprovider                 # 396 passed, 11 skipped, 0 failed  (exit 0)

# --- frontend ---
cd ..\frontend
npm test                                                # 18 files / 86 passed (exit 0)
npm run build                                           # tsc -b && vite build (exit 0)
```

Test-suite safety: `backend/tests/conftest.py` blocks non-local `DATABASE_URL`; set
`$env:ALLOW_REMOTE_TEST_DB='1'` only for a deliberately chosen staging database.

---

## 8. Local vs . deployed

| | Value |
| --- | --- |
| Local branch / HEAD | `main` @ `aca01b9` |
| Remote `origin` HEAD | `aca01b9` — **identical to local HEAD** |
| Deployed code | The remote head is the pre-fix code; **none of the fixes in this audit are deployed** |
| Working tree | All fixes are **uncommitted** (see §4); no commit/push/deploy was performed |

So the fixes and the green suites above describe the **local working tree only**. Anyone
consuming the deployed site is still running the unfixed `aca01b9`.

---

## 9. Not validated / remaining blockers

### 9.1 Deploy-blocker found and fixed — migration `010` idempotency

`ip_record.is_archived` is selected on every `IpRecord` query, and the repo ships a one-off
script `backend/migrate_add_is_archived.py` documented to add the column **to the live (Neon)
database** out-of-band (`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`) without bumping the Alembic
revision. Production therefore already has the column while its revision is behind head.

The first version of migration `010` used a plain `op.add_column` / `op.create_index`, so the
Render `preDeployCommand` (`alembic upgrade head`) would have aborted on the next deploy with
`column "is_archived" of relation "ip_record" already exists`.

**Fix (this audit):** `010` now issues `ADD COLUMN IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS`
(mirroring `migrate_add_is_archived.py`). Verified on a disposable DB that had been upgraded to
revision `008` and then given `is_archived` out-of-band (simulating production): `alembic upgrade
head` completed `008 → 009 → 010`, exit 0; re-running the migration SQL when the column/index
exist is a no-op. On a fresh DB the column/index are still created. Non-destructive either way.

### 9.2 Other open items

- **Not validated (no authorised access / would touch prod):** the 11-agent OCR pipeline
  end-to-end against real certificates, IP India / InPASS verification, OCR.Space fallback,
  SMTP password-reset email delivery, and Playwright browser E2E.
- **Local patent/design files.** `C:\Users\mohan\Downloads\New folder (2)` contains
  **7 PDFs (~28.85 MB)** — design/patent certificates and one publication page. They were
  inventoried (metadata only; no contents exposed). They were **not** pushed through the
  pipeline, because doing so requires running the app + Tesseract/OCR and writing to local
  storage, and external verification is not authorised. This remains an open verification
  item for a controlled local run.
- **Schema drift check.** The repo ships no drift tool (`scripts/verify_tables.py` is a
  scratch script with a hard-coded DSN). Drift was therefore checked with a disposable
  temp script (`inspect()` vs `Base.metadata`): **23 model tables, 0 missing tables,
  0 missing columns → no drift.** The check is not committed.
- **P3 open item:** `005_*` `alembic downgrade` fails (unnamed FK, `op.drop_constraint(None, …)`).
  Forward upgrades are unaffected.
- **Deployed build identity** cannot be proven from deployment metadata; the only hard fact
  is that remote HEAD == local HEAD == `aca01b9` (unfixed).
