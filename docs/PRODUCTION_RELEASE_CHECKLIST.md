# PRODUCTION RELEASE CHECKLIST & ROLLBACK PLAN

**Project:** Faculty Patent Collection & Verification Portal
**Scope:** Release of the **uncommitted local fixes** (workflow rules A–F, migration
`007a`/`010`, test-isolation changes) over the deployed revision `aca01b9`.
**Status:** DRAFT — **NOT EXECUTED.** No commit, push, deploy, migration, or production
data change was performed while writing or validating this document.

> **Do not print, paste, or commit secret values.** This checklist refers to secrets by
> **variable name only**. Read them from the platform secret store at deploy time.

---

## 0. Gate: what must be true before *starting* the release

- [ ] **The fixes are committed and pushed.** They are currently **untracked/modified**
      in the working tree. A Render build made from the remote repo would **not** contain
      `backend/alembic/versions/007a_add_hod_admin_to_user_role.py`,
      `010_add_ip_record_is_archived.py`, the hardened endpoints, or the HOD read-only UI.
      *Release from `aca01b9` would ship the unfixed system.*
- [ ] Local pre-flight green (see §3): backend `396 passed`, frontend `86 passed`,
      `npm run build` ok, `alembic current` = `010 (head)`.
- [ ] Change owner signs off that the tree being released is exactly the validated tree
      (record the commit SHA produced by the commit step).

---

## 1. Required environment variables & secret configuration

Set these in the **Render dashboard secret store** (never in `render.yaml`, never in git).
`render.yaml` already declares non-secret values; secrets are `sync: false` / `generateValue`.

| Variable | Required in prod | Notes |
| --- | --- | --- |
| `APP_ENV` | yes | must be `production` (declared in render.yaml) |
| `SECRET_KEY` | yes (secret) | `generateValue: true` in render.yaml — Render generates & keeps it |
| `DATABASE_URL` | yes (secret) | Neon `postgresql+asyncpg://…neon.tech/neondb?sslmode=require` |
| `CORS_ORIGINS` | yes (secret-ish) | the real `https://<frontend-origin>`; **no `*`** |
| `COOKIE_SECURE` | yes | `true` |
| `COOKIE_SAMESITE` | yes | `none` (cross-domain frontend) |
| `LOCAL_STORAGE_ROOT` | yes | `/data/storage` — see §4 (durability blocker) |
| `WEB_CONCURRENCY` | yes | `2` |
| `SMTP_ENABLED` + `SMTP_HOST/PORT/USERNAME/PASSWORD/FROM_EMAIL` | for password reset | if unset, `forgot-password` returns `503 EMAIL_UNAVAILABLE` (honest, not a crash) |
| `FRONTEND_RESET_URL` | for password reset | **must** be the prod frontend origin, not localhost |
| `OCSPACE_API_KEY` (`OCRSPACE_API_KEY`) | optional | leave blank for fully-offline local OCR |
| `IPINDIA_ENABLED` / `IPINDIA_SEARCH_URL` | optional | leave disabled for manual verification |

**Startup fail-fast** (`app/core/config.py`): with `APP_ENV=production` the app refuses to
start unless `SECRET_KEY` is strong (≥32 chars, no dev markers), `COOKIE_SECURE=true`,
`CORS_ORIGINS` has a non-local origin and no `*`, and `DATABASE_URL` is hosted (not
`@localhost`, no `change-me`). **This is a hard gate — a misconfigured deploy fails loudly.**

- [ ] Confirm presence (not values) of every required secret in the dashboard.
- [ ] Confirm `FRONTEND_RESET_URL` points at the deployed frontend if SMTP is enabled.

---

## 2. Database backup & restore validation

Neon provides branching / point-in-time restore (PITR) depending on plan. **Do not rely on
it untested.**

- [ ] **Pre-release backup:** create a Neon branch (or take a snapshot) of the current
      production database immediately before the deploy. Record its name/timestamp.
- [ ] **Restore drill (staging/dev):** restore that branch into a throwaway database and
      confirm the application can read it (`/healthz`, one admin `GET /ip-records`).
- [ ] Confirm who owns the Neon project and can authorize a restore (see §9).
- [ ] Note: the **schema moves forward only** (`upgrade head`). If a migration must be
      undone, the fallback is **restore-from-backup**, because `alembic downgrade` below
      `005` is broken (see §8) and `007a`'s downgrade is a no-op by design.

---

## 3. Migration pre-flight & post-migration checks

`preDeployCommand` runs `alembic -c /app/alembic.ini upgrade head` once per deploy, before
traffic shifts.

**Pre-flight (on a copy, never blindly on prod):**

- [ ] `alembic heads` → exactly one head: `010`.
- [ ] From the current production revision (`008`), the path is `008 → 009 → 010`.
      This has been **validated locally against a simulated production state** (a DB at
      `008` that already had `is_archived` out-of-band): the upgrade completed to `010`,
      exit 0.
- [ ] Migration `007a` (`ALTER TYPE user_role_enum ADD VALUE IF NOT EXISTS 'hod_admin'`) is
      **idempotent** and safe whether or not production already has the label.
- [ ] Migration `009` converts `ip_record.grant_date` and `master_ip_record.grant_date`
      `TIMESTAMP → DATE` (truncates time; production rows hold midnight). Verify no non-midnight
      values are meaningful for your data.
- [ ] Migration `010` is **idempotent** (`ADD COLUMN IF NOT EXISTS` + `CREATE INDEX IF NOT
      EXISTS`). This was changed during this audit precisely because production already has
      `is_archived` out-of-band (added by `backend/migrate_add_is_archived.py`) — a plain
      `ADD COLUMN` would abort the deploy with "already exists".

**Post-migration checks:**

- [ ] Render deploy log shows `Running upgrade 008 → 009` and `009 → 010` (or "no upgrades"
      if already at head) and **no** `already exists` / `DuplicateColumn` errors.
- [ ] `alembic current` (service shell) → `010 (head)`.
- [ ] `ip_record.grant_date` and `master_ip_record.grant_date` are `date`.
- [ ] `ip_record.is_archived` exists, `NOT NULL DEFAULT false`; `ix_ip_record_is_archived`
      present.
- [ ] A model↔schema drift check shows no missing tables/columns (23 model tables).

---

## 4. Durable upload storage & permissions

**This is the most serious production risk.** Uploaded certificates are the portal's core
artifact.

- [ ] **Blocker:** `render.yaml` declares `plan: free` and
      `LOCAL_STORAGE_ROOT=/data/storage` with the comment *"ephemeral on the free plan
      (wiped on redeploy)"*. On the free plan **uploaded files are lost on every
      redeploy/restart**. Records survive in Neon; the PDFs do not.
- [ ] **Decision required before production:** choose one —
      (a) move to a paid Render plan with a **Render Disk mounted at `/data`**, or
      (b) set `STORAGE_BACKEND=s3` and configure durable object storage, or
      (c) explicitly **accept** the loss and document a manual re-upload policy.
      Until one is chosen, storage durability is an **open production blocker**.
- [ ] Verify the runtime user (`appuser`, uid 10001) can write to the storage root.
- [ ] Verify `GET /api/v1/ip-records/{id}/file` serves a previously uploaded file after a
      restart (proves persistence).

---

## 5. Reference-data validation

A freshly migrated DB has **no reference data**; the app does not seed it.

- [ ] Confirm at least one **Department** exists and is `is_active`.
- [ ] Confirm the **`"HOD"` Designation** exists (`Designation.title.upper() == "HOD"`) —
      HOD role assignment keys off it. (Tests must create it; production must already have it.)
- [ ] Confirm a **Super Admin** user exists. The only seed script is
      `backend/create_test_users.py` (3 users; **no departments/designations**) and it is
      **not** wired to `alembic seed` (that command does not exist). Do **not** run it against
      production unless you intend to create/replace those accounts and change the default
      password immediately.
- [ ] Do **not** invent institutional department/designation names. Use the institution's
      real values.

---

## 6. Deployment health checks

- [ ] `GET /healthz` → `{"status":"ok"}` (Render `healthCheckPath`).
- [ ] `GET /readyz` → `{"status":"ready"}`.
- [ ] `GET /metrics` → service name/version.
- [ ] Note: neither `/healthz` nor `/readyz` performs a **database** check; they cannot
      detect a DB outage. Consider adding a DB ping to `/readyz` (backlog).
- [ ] Confirm the container starts with `APP_ENV=production` (fail-fast would otherwise
      reject a bad config).
- [ ] Tail startup logs for the scheduler line and any import/traceback errors.

---

## 7. Post-deploy smoke tests (code deployment)

Run as the relevant roles; a hidden UI control is **not** proof of authorization — use the
APIs where possible.

**Upload + status polling**
- [ ] Faculty uploads a valid PDF → `202`; `GET /uploads/{id}/status` shows the 11-agent
      `jobs` trail progressing to completion.

**Faculty association (rule A/B)**
- [ ] Uploader is auto-associated (no self-accept button).
- [ ] Uploader sends a request to **another internal faculty** only → `201`.
- [ ] A **non-uploader** calling `POST /associations/` → **403**.
- [ ] A request addressed to an **HOD** → **422**.

**HOD read-only (rule D)**
- [ ] HOD can list department documents/duplicates/conflicts (read-only) and
      `GET /verification/institutional/{id}` → `200`.
- [ ] HOD `POST /verification/institutional/{id}` → **403**.
- [ ] HOD `POST /duplicates/{id}/resolve` and `/conflicts/{id}/resolve` → **403**.
- [ ] HOD `POST /associations/{id}/respond` → **403**.

**Super Admin grant (rule E)**
- [ ] `POST /admin/ip-records/{id}/grant` without `confirm:true` → `422`.
- [ ] Grant on a not-eligible record → the specific `GRANT_*` error (not a 500).
- [ ] Grant on an eligible record → `GRANTED`; audit row `PATENT_GRANTED` written.
- [ ] Super Admin retains duplicate/conflict resolution → `200`.
- [ ] Super Admin has **no** association accept/reject surface.

**Auth/security**
- [ ] State-changing request without CSRF (cookie auth) → `400`; with Bearer → allowed.
- [ ] Deactivated account cannot log in or act.

---

## 8. Monitoring & error-log review

- [ ] Watch Render logs for the first 15 minutes after deploy: 5xx rate, unhandled
      tracebacks (the global handler prints full tracebacks to logs), CSRF/rate-limit spikes.
- [ ] `GET /metrics` reachable for scrapers.
- [ ] Review any `INTERNAL_ERROR` (500) entries — the client sees only a generic message,
      so real causes are only in logs.
- [ ] Confirm scheduled jobs (APScheduler) start once (idempotent start was fixed).

---

## 9. Rollback plan

**Rollback criteria (any one triggers rollback):**
- `preDeployCommand` migration fails (deploy aborts — no traffic shift; safe).
- Post-deploy smoke test fails for association / HOD read-only / grant gates.
- Sustained 5xx spike or the app fails to become healthy.

**Who must authorize:** the repository owner **and** the Super Admin / DBA responsible for
the production Neon database. A database restore additionally requires the Neon project owner.
**No single individual performs a database rollback without the second authorization.**

**Code rollback**
- [ ] Render: **Roll back to the previous deploy** (the prior image at `aca01b9`). Code
      rollback is fast and does not touch the DB.

**Database rollback (only if a migration caused damage)**
- [ ] Because the schema moves forward and downgrade below `005` is broken, the safe path is
      **restore from the pre-release Neon branch/snapshot** (§2), not `alembic downgrade`.
- [ ] If restore is required, accept that writes after the snapshot are lost; coordinate a
      maintenance window and re-run smoke tests.

**Known downgrade limitation (P3, documented):** `backend/alembic/versions/005_*.py:63`
calls `op.drop_constraint(None, ...)` (unnamed FK) and cannot compile, so `alembic downgrade`
below `005` fails. Forward upgrades are unaffected.

---

## 10. Post-deployment verification: code vs external integrations

Distinguish clearly:

| Layer | How to verify | Status after this release |
| --- | --- | --- |
| **Code deployment** (workflow rules A–F, migrations, HOD read-only UI) | The smoke tests in §7 via the deployed API/UI | Verifiable at deploy time |
| **External integrations** | live authenticated calls | **NOT verifiable here** |
| — IP India / InPASS official verification | needs authorised endpoint/credentials | Unverified; disabled by default (`IPINDIA_ENABLED=false`) |
| — OCR.Space fallback | needs `OCRSPACE_API_KEY` | Unverified; leave blank for offline OCR |
| — SMTP password-reset email | needs SMTP credentials | Unverified; returns `503` until configured |
| — Browser E2E (Playwright) | needs a running browser+server | Not run in this audit |
| — Real certificate OCR | needs the actual certificates + a controlled run | Not run; 7 local PDFs inventoried only |

- [ ] Record which of the above were exercised; do **not** mark an integration "working"
      because the code path exists.

---

## 11. Security/operational finding classification (from `docs/ENGINEERING_AUDIT.md`)

| Finding | Classification | Rationale |
| --- | --- | --- |
| Migration `010` non-idempotent (deploy abort on prod) | **Must fix before production** — **FIXED in this audit** | Prod already has `is_archived`; now `IF NOT EXISTS`. Verified on a simulated prod DB. |
| Uncommitted fixes not in the deployable revision | **Must fix before production** | Commit required; deploying `aca01b9` ships the unfixed system. |
| Ephemeral upload storage on Render free plan | **Must fix before production (or owner accepts risk)** | Core artifacts lost on redeploy. See §4. |
| No reference-data seed for departments/designations | **Requires owner/product decision** | Institutional values must be real; validate presence (§5). |
| Refresh-token rotation/revocation absent | **Requires owner/product decision** (security hardening) | Stolen refresh token reusable until expiry; acceptable documented limitation for MVP if accepted. |
| Upload dimension/page validation is fail-open | **Acceptable documented limitation / owner decision** | Unparseable files bypass page/dimension limits; extension+magic+size still enforced. Fix if untrusted uploads. |
| Raw backend payloads rendered in some UI errors | **Acceptable documented limitation** | UX/clarity; no secret exposure. Track in frontend data-layer backlog. |
| `005` downgrade broken | **Acceptable documented limitation** | Downgrade-only; forward upgrades fine; rollback via backup (§9). |
| Grant authz/audit (row lock + 10 gates) | **OK** | Verified server-side; audit `PATENT_GRANTED` written. |
| Storage backup/restore readiness | **Requires owner/product decision** | Depends on Neon plan; drill required (§2). |
| IP India / OCR.Space / SMTP / browser E2E | **Requires authorized external integration testing** | Cannot be validated without credentials/authorized access. |

---

## 12. Sign-off (to be completed at release time)

| Role | Name | Decision | Timestamp |
| --- | --- | --- | --- |
| Repository owner | | | |
| Super Admin / DBA (DB changes) | | | |
| Product owner (storage/reference-data decisions) | | | |

**Nothing in this checklist has been executed. No commit, push, deploy, or production
migration was performed.**
