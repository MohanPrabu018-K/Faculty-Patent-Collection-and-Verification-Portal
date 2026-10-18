# HANDOFF — Faculty Patent Collection & Verification Portal

- **Document authored:** 2026-10-11 (local shell date)
- **Repository root:** `E:\Faculty profile portal`
- **Branch / HEAD:** `main` @ `aca01b9`  (remote `origin` HEAD is the **same** commit)
- **Document status:** UNCOMMITTED, UNTRACKED. Nothing in this session was committed,
  pushed, deployed, or applied to production data.

> **Two-state warning.** Everything below describes the **local working tree**, which is
> ahead of the deployed code. The remote/deployed revision is still `aca01b9` (pre-fix).
> None of the workflow/authorization fixes or test fixes described here are deployed.

---

## 1. Summary

The portal (FastAPI async + Postgres backend; React 19 / Vite / TypeScript frontend)
collects patent/design certificates, runs an in-process OCR pipeline, collects explicit
association confirmations from named internal faculty, exposes records read-only to HODs,
and ends in a single **Super Admin Grant** action.

This session completed three things:

1. **Fixed the five previously-failing backend tests** at the fixture level (deterministic,
   no weakened assertions), taking the full suite from `350 passed, 5 failed, 43 errors`
   to **`396 passed, 11 skipped, 0 failed, 0 errors` (exit 0)**.
2. **Hardened the association/HOD workflow** to the authoritative business rules (A–F):
   uploader-only dispatch, HOD strictly read-only for verification + duplicate/conflict
   resolution, all enforced server-side and covered by regression tests that hit the APIs.
3. **Repaired the database provisioning path** (migrations that could not build a DB from
   scratch) and the test-isolation safety net (local-DB guard, idempotent scheduler).

| Check | Result | Exit |
| --- | --- | --- |
| Backend suite (`python -m pytest -q`) | **396 passed, 11 skipped, 0 failed** | 0 |
| Frontend (`npm test`) | **18 files / 86 tests passed** | 0 |
| Frontend build (`npm run build`) | **tsc -b clean, vite build ok** | 0 |
| Alembic `current` / `heads` | **`010 (head)` / `010 (head)`** — single head | — |
| Model↔schema drift (23 tables) | **none** (0 missing tables, 0 missing columns) | — |

---

## 2. Database / migration status (local only)

- Fresh `alembic upgrade head` on a disposable local DB succeeds to **`010`**.
- Chain: `001 → 002 → 003 → 52ce3b033131 → 005 → 006 → f5cfdeecb51b → 007 → 007a → 008 → 009 → 010`.
- Two migrations were added to make a from-scratch DB buildable:
  - `007a_add_hod_admin_to_user_role.py` — adds `hod_admin` to `user_role_enum` (`008` had
    required it but no migration ever created it).
  - `010_add_ip_record_is_archived.py` — adds `ip_record.is_archived` (+ index), the **only**
    column the ORM selected on that no migration created.
- `008.down_revision` re-pointed to `007a`.
- The repo has **no** drift tool; drift was verified with a disposable temp script. Not committed.
- **Never** point Alembic at the root `.env` (production Neon). Tests refuse a non-local DB
  unless `ALLOW_REMOTE_TEST_DB=1` is set deliberately.
- **P3 open:** `005_*` `alembic downgrade` fails on an unnamed FK (`op.drop_constraint(None,…)`).
  Forward upgrades unaffected.

Local DB used: `postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/faculty_portal_migtest`.

---

## 3. Business workflow — authoritative rules (A–F) and where they are enforced

| Rule | Requirement | Enforcement | Verdict |
| --- | --- | --- | --- |
| **A** | Uploader auto-associated server-side; no acceptance step; idempotent on retries | Upload auto-associates uploader; `POST /associations/` rejects the uploader as recipient | ✅ |
| **B** | Other internal faculty get explicit requests; recipient-only decisions; authz/ownership/status/dup/audit | `POST /associations/` (uploader-only), `{id}/respond` (recipient-only; HOD responder 403) | ✅ |
| **C** | Externals excluded from internal faculty/HOD/identity flows; data preserved | `_other_internal_reviewers` excludes externals/inactive/HOD | ✅ |
| **D** | HOD strictly **read-only** (association decisions, institutional verification, dup/conflict resolve); dept scope server-side | Institutional verify → `super_admin`; `duplicates.py`/`conflicts.py` resolve → `super_admin`; HOD GETs dept-scoped read-only | ✅ |
| **E** | Super Admin has **no** association Accept/Reject; only the final, fully-gated Grant | No SA association-decision endpoints; grant gated (row lock + 10 gates) | ✅ |
| **F** | All rules backend-enforced; IDOR/privilege-escalation/invalid-transition/cross-dept/dup prevented | Ownership + dept checks, state machine, row lock, single-active-HOD DB index | ✅ |

**Hardening applied this session (all uncommitted):**

- `backend/app/api/associations.py` — missing record → 404; non-uploader → 403; HOD recipient → 422;
  HOD responder → 403.
- `backend/app/api/faculty.py` — legacy `/{record_id}/associate/{other_faculty_id}` got the same
  uploader-only + HOD-recipient hardening.
- `backend/app/api/verification.py` — institutional verification is Super-Admin only; HOD branch
  removed (HOD keeps the read-only, department-scoped GET).
- `backend/app/api/duplicates.py` / `conflicts.py` — resolve/dismiss is Super-Admin only.
- Frontend — `features/hod/HodPages.tsx` Duplicates/Conflicts are read-only; `api/client.ts`
  HOD resolve wrappers removed. Super Admin still resolves via `features/admin/AdminQueuesPage.tsx`.

**Regression coverage:** `test_association_lifecycle.py` (uploader-only, HOD-recipient 422,
HOD-respond 403), `test_hod_manual_verification.py::test_hod_cannot_verify_readonly`,
`test_staged_workflow.py::test_admin_verify_blocked_with_exact_counts`,
`test_batch12_fixes.py::TestHodReadOnlyResolutionDenied` (HOD 403 on both resolve endpoints,
state unchanged, Super Admin 200).

---

## 4. Grant decision (Super Admin only, server-side)

`POST /api/v1/admin/ip-records/{record_id}/grant` requires `confirm: true`; takes a
`SELECT … FOR UPDATE` row lock; rejects already-granted, non-`VERIFIED`, invalid transitions,
pending internal approvals, inactive/missing uploader, open duplicate/conflict, incomplete
processing, and missing official identifier — with a specific error code per gate. On success
it records `GRANTED` transactionally and audits `PATENT_GRANTED`.

---

## 5. Test evidence (this session, local)

Focused (before the final full run):

```
tests/test_admin_governance.py::TestHodUniqueness
tests/test_batch12_fixes.py::TestDisplayNamesEnriched
tests/test_hardening.py::test_processing_job_agent_trail_per_record
→ 9 passed  (exit 0)
```

Rule-D addition:

```
tests/test_batch12_fixes.py::TestHodReadOnlyResolutionDenied → 1 passed (exit 0)
```

Full suite (from `backend`, local DB):

```
python -m pytest -q -p no:cacheprovider
→ 396 passed, 11 skipped, 0 failed, 0 errors  (exit 0, ~174s)
```

Frontend:

```
npm test        → 18 files / 86 tests passed  (exit 0)
npm run build   → built ok (exit 0)
```

The 5 baseline failures were fixed at the fixture level:

| Test | Root cause | Fix |
| --- | --- | --- |
| `TestHodUniqueness` ×3 | No `"HOD"` `Designation` row on a fresh DB | Autouse fixture creates it idempotently, removes only if it created it |
| `TestDisplayNamesEnriched` | Records seeded in `VERIFICATION_REQUIRED`, which HOD documents-visibility hides | Seed at `FACULTY_ASSOCIATION_COMPLETE` |
| `test_processing_job_agent_trail_per_record` | Non-hermetic; scanned pre-existing rows (empty on fresh DB) | Seed a record + 11 real agent `ProcessingJob` rows; assert the `/uploads/{id}/status` trail; clean up in `finally` |

The 43 baseline errors were `SchedulerAlreadyRunningError` from repeated app lifespans, fixed
by making the scheduler lifespan idempotent.

---

## 6. Not validated / blockers

- **Not validated (no authorised access / would touch prod):** real-certificate OCR pipeline,
  IP India / InPASS, OCR.Space fallback, SMTP password-reset delivery, Playwright browser E2E.
- **Local certificate files:** `C:\Users\mohan\Downloads\New folder (2)` — **7 PDFs (~28.85 MB)**
  (patent/design certificates + one publication page). Inventoried only (metadata, no contents).
  Not pushed through the pipeline (needs app+OCR+storage run; external verification unauthorised).
- **Deployed build identity** unprovable from metadata; only fact is remote HEAD == `aca01b9`.
- **P3:** `005` downgrade bug; no ESLint/`noUnusedLocals`; refresh-token rotation absent.

---

## 7. Local vs . deployed

| Item | Local working tree | Deployed / remote |
| --- | --- | --- |
| Revision | `main` @ `aca01b9` + uncommitted fixes | `main` @ `aca01b9` (no fixes) |
| Workflow hardening (A–F) | Present, tested | **Absent** |
| Migration `007a` / `010` | Present, applied locally | **Absent** |
| Pre-fix 5 failing tests | Fixed | n/a (repo state) |
| Backend suite | 396 passed / 0 failed | (not run against deployed) |

Nothing was committed, pushed, or deployed in this session.

---

## 8. Exact reproduction commands

```powershell
# from repo root
$env:DATABASE_URL='postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/faculty_portal_migtest'
.\backend\.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head
.\backend\.venv\Scripts\python.exe -m alembic -c alembic.ini current   # 010 (head)
.\backend\.venv\Scripts\python.exe -m alembic -c alembic.ini heads     # 010 (head)

cd backend
python -m pytest -q -p no:cacheprovider                                # 396 passed, 11 skipped

cd ..\frontend
npm test                                                               # 18 files / 86 passed
npm run build                                                          # tsc -b && vite build
```
