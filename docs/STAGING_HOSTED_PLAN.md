# Hosted staging plan (Phase 2B) — prepare, do **not** execute

> **STOP LINE.** Nothing in this document has been created or changed on any
> hosted provider. No Render service, Render/Neon Postgres, Pages project, DNS
> record, credential, account, migration or deployment exists because of this
> phase. Every remote step below is a proposal that requires explicit owner
> approval (see §12). Phase 2B is read-only against hosted systems.

Companion docs: `docs/STAGING_SETUP.md` (Phase 2A tooling) and
`docs/STAGING_TEST_DATA.md` (account/record matrix).

---

## 1. Objective

Run the authenticated rule matrix (A–F) against a **hosted** stack that runs the
**approved commit**, using real Chromium via the existing Playwright staging
project, **without touching production** and **without weakening any guard**.

## 2. Pinned artifact

| Item | Value |
| --- | --- |
| Approved commit | `8503fe54a7640ba6e57995ccee79f8d174d46ad5` |
| Repo HEAD (local) | same commit, clean except the uncommitted Phase 2A/2B files |
| Frontend already live (prod) | build of `8503fe5` (asset hashes verified in Phase 1) |
| Backend already live (prod) | **commit unknown** (version skew risk) |

Hosted staging exists to remove the "backend commit unknown" ambiguity by
deploying a **named** commit. `render.yaml` sets `autoDeploy: false`, so the
staging service must be deployed manually to the pinned SHA.

## 3. Architecture

```
                    VITE_API_BASE_URL (build-time)
 Browser ──► Staging frontend ───────────────► Staging backend (FastAPI)
             separate Pages project            Render web service
             faculty-portal-staging.pages.dev  faculty-portal-api-staging.onrender.com
                                                        │ DATABASE_URL (TLS)
                                                        ▼
                                                  Staging PostgreSQL
                                                  (separate instance/branch)
                                                        ▲
                                                        │ STAGING_DATABASE_URL
                              operator tooling (provision / teardown) ──┘
```

Component isolation rules:

* **Backend**: a *second* Render service built from the same Dockerfile; it never
  shares env vars, secrets or `DATABASE_URL` with production.
* **Database**: a *separate* Postgres instance/branch; never the production
  database or a production branch. No production data is copied in.
* **Frontend**: a *separate* Pages project (or a dedicated non-`production`
  branch alias). The production Pages project's env vars are not modified.
* **Storage**: `LOCAL_STORAGE_ROOT` on the Render service is **ephemeral** (free
  plan has no disk). Acceptable for throwaway staging uploads; not for anything
  that must survive a restart.
* **No production credentials** are reused anywhere in the staging stack.

## 4. Environment variables (names only — values never recorded here)

### 4.1 Staging backend (Render dashboard)

`APP_ENV`, `DATABASE_URL`, `SECRET_KEY`, `CORS_ORIGINS`, `COOKIE_SECURE`,
`COOKIE_SAMESITE`, `E2E_TEST`, `LOCAL_STORAGE_ROOT`, `OCRSPACE_API_KEY`
(optional). Required values are tabulated in `docs/STAGING_SETUP.md` §3.1.
`COOKIE_SAMESITE=none` is mandatory for the hosted (cross-site) profile.

Optional/quiet-staging knobs (confirm the exact names in `config.py` before
use): SMTP/notification settings kept **off** so staging cannot email anyone,
and the scheduler settings if background reminder jobs should be disabled.

### 4.2 Staging frontend (Pages build env)

`VITE_API_BASE_URL` (must include `/api/v1`).

### 4.3 Operator tooling (local shell only, never deployed)

`STAGING_DATABASE_URL`, `STAGING_ALLOW_REMOTE_DB`, `STAGING_DB_HOST_ALLOWLIST`,
`STAGING_CONFIRM`, `STAGING_FRONTEND_URL`, `STAGING_API_URL`,
`STAGING_ALLOWED_HOSTS`. (If a Path-B guard extension were ever approved, it
would add `STAGING_ALLOW_HOSTED_DB` and `STAGING_PRODUCTION_DB_HOSTS` — see §5.)

These live in a git-ignored `scripts/staging/hosted.env` (added to `.gitignore`
this phase).

## 5. Guard review — the one hard blocker

### 5.1 DB guard (`scripts/staging/guard.py`): allowlist cannot reach production ✅

Measured behaviour (also encoded in `scripts/staging/test_guard.py`, **19 tests,
all passing**):

| Target | no opt-in | opt-in + exact allowlist |
| --- | --- | --- |
| loopback `127.0.0.1/faculty_portal_staging` | OK | OK |
| Render **internal** host `dpg-…-a` | REFUSED | **OK** |
| Render **public** host `dpg-…-a.oregon-postgres.render.com` | REFUSED | **REFUSED** |
| Neon **public** host `ep-….aws.neon.tech` | REFUSED | **REFUSED** |
| Supabase `db.….supabase.co` | REFUSED | **REFUSED** |
| non-marker remote `staging-db.internal.example.net` | REFUSED | **OK** |
| reserved DB name `neondb` (on an allow-listed host) | REFUSED | **REFUSED** |
| non-disposable name `customers` | REFUSED | **REFUSED** |

Conclusions:

* The managed-cloud markers are checked **before** the allowlist, so the
  allowlist can **never** be configured to reach a production/managed host. The
  reserved-name deny-list is checked **after** the allowlist, so even an
  allow-listed host cannot use `neondb`/`faculty_portal`/… The guard was **not
  weakened**.
* The tooling reads **only** `STAGING_DATABASE_URL` and never falls back to
  `DATABASE_URL` (tested).
* **Consequence:** the repo's intended hosted provider (Render Postgres, or a
  Neon branch) is **unreachable from the operator machine over its public
  hostname.** `docs/STAGING_SETUP.md` §6 step 5 as originally written was
  therefore not achievable. This is the blocker to resolve.

### 5.2 Playwright guard (`frontend/tests-staging/guard.ts`): hosted staging ✅

Measured locally: with `STAGING_FRONTEND_URL=https://faculty-portal-staging.pages.dev`,
`STAGING_API_URL=https://faculty-portal-api-staging.onrender.com` and both hosts
in `STAGING_ALLOWED_HOSTS`, the guard self-checks pass **7/7**; with a production
host, config load aborts before any test runs (exit 1). So the Playwright project
**supports** hosted staging with an allowlist. (The prose in
`STAGING_SETUP.md` §4.2 overstated the refusal; corrected in this phase.)

### 5.3 Resolution options for the DB-guard blocker

| Path | How | Guard change | Notes |
| --- | --- | --- | --- |
| **A. In-network provisioning** | Run `provision_staging.py` from *inside* the Render network against the DB's **internal** hostname (`dpg-…-a`), with opt-in + allowlist | none | The `scripts/` dir is **not in the Docker image**, and the internal host is unreachable off-network, so this needs an in-container one-off job with the script shipped in. Verify provider shell/job capability first. |
| **B. Narrow guard extension** | Allow an **explicitly acknowledged** provider host, with the real production host pinned as an absolute deny | **yes** (approval) | Only option that uses the documented provider over its public host. Introduces operator-declared production identity into the guarantee — i.e. conditional, not static. Diff in §15.1; **not applied.** |
| **C. Non-marker staging DB** | Point `STAGING_DATABASE_URL` at a staging Postgres whose hostname is **not** on the marker list (self-managed, or an alternative managed provider) | none | Zero guard change. Requires a hosting decision (cost/permissions) — see §11. |

**Recommendation (resolved in Phase 2C — see
`docs/STAGING_PROVISIONING_INVESTIGATION.md`):** prefer **C**, with **A** as the
higher-isolation alternative. Verified from official provider docs:

* **A** is gated on a **paid** Render web service plan (Shell + one-off jobs are
  paid-only; free web services can only *send* private-network traffic), or on the
  one-time-only `initialDeployHook`. It also needs a Dockerfile change (`scripts/`
  is not in the image) **and** a credential/fixture-retrieval change (the
  generated passwords + `.staging-fixtures.json` are written inside the container
  and are unreadable by the operator). Path A therefore cannot be run as-is.
* **C** keeps the guard and the entire tested provisioning flow **unchanged**, needs
  no paid Render compute and no image change. The trade-off is a
  publicly-reachable staging DB (TLS + credentials + provider firewall) — the same
  posture as production's Neon DB. Path C's exact host/name requirements are
  enumerated in the investigation doc §4.1.

Use **B** only if the owner specifically wants Render/Neon staging **and**
accepts the guard extension; if so, review the §15.1 diff (default-off, additive,
with tests proving the declared production host is still refused).

## 6. Exact manual setup sequence (each step gated on approval)

| # | Action | Approval |
| --- | --- | --- |
| 0 | Resolve §5 (choose Path A/B/C) and §11 (hosting permissions/cost) | required |
| 1 | Create staging Postgres (separate instance/branch); record its host + DB name | required |
| 2 | Apply the chosen provisioning path's guard-compatible settings | required |
| 3 | Create Render web service `faculty-portal-api-staging` (same Dockerfile, `autoDeploy: false`, `healthCheckPath: /healthz`) | required |
| 4 | Set §4.1 env vars in the service dashboard (incl. `COOKIE_SAMESITE=none`) | required |
| 5 | Set `preDeployCommand` = `alembic -c /app/alembic.ini upgrade head` | required |
| 6 | Deploy the pinned commit `8503fe54…` | required |
| 7 | Verify `/healthz` and `/readyz` (see §7 caveat) and that `/docs` behaviour matches the §15.2 decision | required |
| 8 | Create separate Pages project `faculty-portal-staging` with `VITE_API_BASE_URL` = staging API + `/api/v1`, built from the pinned commit | required |
| 9 | Set backend `CORS_ORIGINS` to the exact Pages origin; add both hosts to `STAGING_ALLOWED_HOSTS` | required |
| 10 | Provision data (see §8); write `.staging-fixtures.json` | required |
| 11 | Run `npx playwright test -c playwright-staging.config.ts` (see §8.3) | required |
| 12 | Tear down (see §8.4) or leave running for review | required |

## 7. Migrations & startup health checks

* **Migrations**: `preDeployCommand` runs `alembic -c /app/alembic.ini upgrade head`
  (same as production). It fails the deploy if the DB is unreachable, which is
  the real connectivity gate. Migration head is `010`.
* **Rollback caveat**: migration `005`'s downgrade is broken, so DB rollback =
  recreate the staging DB and re-run `upgrade head`. Never `downgrade`.
* **`/healthz`** is a static `{"status":"ok"}` and `/readyz` is a static
  `{"status":"ready"}` — **neither checks the database** (confirmed in
  `backend/app/main.py`). A staging deploy can be "healthy" with a bad
  `DATABASE_URL`. Recommended hardening (separate change, not applied): make
  `/readyz` issue a trivial `SELECT 1`.

## 8. Provision / seed / teardown on hosted

### 8.1 Provisioning
`python scripts/staging/provision_staging.py` — **omit `--create-database`** for
managed Postgres (the DB and role already exist, and the role may lack
`CREATEDB`). Keep `--migrate` only if the pre-deploy step did not run. The script
upserts three staging departments, two designations, 15 synthetic accounts
(`stg.*@staging.example.com`) and deterministic `stg-rec-*` scenario records, and
is **idempotent**.

### 8.2 Cleanup
`teardown_staging.py` is dry-run by default and deletes **only** rows whose id
starts with `stg-`; it never deletes pre-existing/non-`stg-` rows.

### 8.3 Running the suite
```powershell
$env:STAGING_CONFIRM='1'
$env:STAGING_FRONTEND_URL='https://faculty-portal-staging.pages.dev'
$env:STAGING_API_URL='https://faculty-portal-api-staging.onrender.com'
$env:STAGING_ALLOWED_HOSTS='faculty-portal-staging.pages.dev,faculty-portal-api-staging.onrender.com'
cd frontend
npx playwright test -c playwright-staging.config.ts
```

### 8.4 Teardown
Dry-run first, then `--yes`, then verify all `stg-` counts are `0`. Also delete
the hosted resources (§12 approvals) so staging cannot linger with `E2E_TEST=1`.

## 9. Credentials & secrets handling

* Synthetic identities only; emails under `@staging.example.com`.
* Passwords are generated locally and written **only** to git-ignored files
  (`staging_accounts.local.json`, `.staging-fixtures.json`). Never committed.
* No production secret is reused: fresh `SECRET_KEY`, fresh DB, fresh Pages
  project.
* Rotate/tear down after QA.

## 10. CSRF / session / CORS compatibility

* **CORS**: `CORS_ORIGINS` must be the exact staging Pages origin (https, no
  `*`); `allow_credentials=True` is already set. The guard in `config.py`
  enforces a non-local https origin for `APP_ENV=staging`.
* **CSRF**: `/api/v1/auth/*` is exempt; valid Bearer tokens are exempt;
  cookie-only non-GET without `X-CSRF-Token` ⇒ `400 CSRF_TOKEN_INVALID`. The
  staging HTTP client sends Bearer + `X-CSRF-Token` and talks directly to the API
  origin, so it does not depend on cross-site cookie behaviour.
* **Session**: `POST /auth/refresh` reads the `access_token` **cookie**; hence
  `COOKIE_SAMESITE=none` + `COOKIE_SECURE=true` are required hosted. Third-party
  cookie blocking is a residual risk for the **UI** refresh path only (the API
  matrix uses Bearer).

## 11. Provider costs / permissions / approvals to confirm (do not assume)

**Verified in Phase 2C** (pricing/entitlement from Render's own docs; see
`docs/STAGING_PROVISIONING_INVESTIGATION.md` §2–§3 for citations):

1. A second Render web service: Hobby allows up to **25 services**; Free compute
   keeps it **$0/mo** (paid web compute starts at **$7/mo**, `0.5c-512mb`).
2. A separate Render Postgres: Free plan is **one active DB per workspace**,
   **1 GB**, and **expires 30 days after creation** (14-day grace, then deleted).
   Cheapest paid is **$6/mo** (`0.1c-256mb`).
3. **Shell / one-off Job** (Path A) requires a **paid web service compute plan**;
   free web services explicitly cannot run one-off jobs or open a shell. A
   free-compatible alternative is the one-time `initialDeployHook` (seeds once,
   cannot re-run or tear down).

Still **unknown** and to be confirmed before any remote action:

4. Cloudflare Pages: a separate project (or a non-production branch alias) and
   the ability to set a different `VITE_API_BASE_URL` without touching the
   production project.
5. If Path C is chosen: which alternative DB provider, and that provider's
   account/permission/cost (Render's own pricing above does **not** apply).
6. Domain/DNS ownership if a custom staging hostname is desired (not required —
   provider default hostnames suffice).
7. Whether staging must be access-restricted (Cloudflare Access / IP allow-list)
   given `E2E_TEST=1`.

## 12. Approvals required before **any** remote action

* Approve hosted staging at all, and the chosen §5 path (A/B/C).
* Approve creating: one Render web service, one Postgres instance/branch, one
  Pages project (or branch alias).
* Approve deploying commit `8503fe54…` to staging.
* Approve running provisioning/teardown (they write to the staging DB only).
* Approve the §11 cost/permission answers.
* Separately approve (or reject) the §15 proposed code/config diffs.

## 13. Files changed / proposed in Phase 2B

Changed (local, uncommitted):

* `.gitignore` — ignore hosted operator env files.
* `docs/STAGING_SETUP.md` — corrected Playwright-guard description; added
  `COOKIE_SAMESITE` + `E2E_TEST` caution; added hosted-provider consequence to
  the DB guard; corrected §6.
* `scripts/staging/test_guard.py` — **new** local guard test-suite (19 passing).

Proposed (review only, **not** created/applied): `render.staging.yaml` (§15.3)
and the guard/`/docs` diffs (§15.1–15.2).

## 14. Remaining technical & operational blockers

1. **DB-guard vs hosted provider** (§5) — the single hard technical blocker.
2. **Backend commit unverifiable** — resolved only by deploying the pinned SHA.
3. **Faculty IDs missing** from all source documents — real (non-synthetic)
   identity tests need institution-supplied IDs.
4. **`/docs` + `/openapi.json` public** on production (recommendation §15.2).
5. **`/readyz` does not check the DB** (§7).
6. **Unseeded required reference data** (departments, `HOD` designation,
   super-admin) on any fresh DB — handled by provisioning on staging; still a
   production concern.
7. **Provider plan/permission unknowns** (§11).
8. **Backup/restore drill** and **external-integration authorization**
   (IP India/InPASS, OCR.Space, SMTP) remain out of scope/blocked.

## 15. Proposed diffs for review (NOT applied)

### 15.1 Optional, approval-gated guard extension (Path B only)

Additive and **default-off**; without the two new env vars, behaviour is
byte-for-byte identical to today. The declared production host is refused
**before** any marker logic, so there is no override for it.

```diff
--- a/scripts/staging/guard.py
+++ b/scripts/staging/guard.py
@@
 DISPOSABLE_DB_MARKERS: tuple[str, ...] = ("staging", "stage", "test", "ci", "disposable", "scratch")
 
+
+def _production_host_denylist() -> set[str]:
+    raw = os.environ.get("STAGING_PRODUCTION_DB_HOSTS", "")
+    return {h.strip().lower() for h in raw.split(",") if h.strip()}
+
 
 class ProductionTargetError(RuntimeError):
@@
-    # Rule 2: production / managed cloud is an absolute refusal.
-    if any(marker in host for marker in PRODUCTION_HOST_MARKERS):
-        raise ProductionTargetError(
-            f"{context}: refusing remote host {host!r} — it matches a production/"
-            "managed-cloud marker. Staging tooling must never touch production."
-        )
+    # Rule 2a: an explicitly declared production host is an absolute refusal.
+    if host in _production_host_denylist():
+        raise ProductionTargetError(
+            f"{context}: refusing host {host!r} — declared in "
+            "STAGING_PRODUCTION_DB_HOSTS. There is no override for production."
+        )
+
+    # Rule 2b: managed-cloud hosts require an explicit, per-host hosted-staging
+    # acknowledgement PLUS a declared production deny-list (fail closed if the
+    # operator has not said what production is).
+    if any(marker in host for marker in PRODUCTION_HOST_MARKERS):
+        hosted_ok = (
+            os.environ.get("STAGING_ALLOW_HOSTED_DB") == "1"
+            and host in _host_allowlist()
+            and bool(_production_host_denylist())
+        )
+        if not hosted_ok:
+            raise ProductionTargetError(
+                f"{context}: refusing remote host {host!r} — it matches a "
+                "production/managed-cloud marker and hosted staging is not "
+                "explicitly acknowledged (STAGING_ALLOW_HOSTED_DB=1 + "
+                "STAGING_DB_HOST_ALLOWLIST + STAGING_PRODUCTION_DB_HOSTS)."
+            )
```

New tests that must accompany it (all must pass):

* declared production host ⇒ refused even with every opt-in set;
* provider host with `STAGING_ALLOW_HOSTED_DB=1` but **empty**
  `STAGING_PRODUCTION_DB_HOSTS` ⇒ refused (fail closed);
* provider host with `STAGING_ALLOW_HOSTED_DB=1` + allowlist + a **different**
  declared production host ⇒ allowed;
* no new env vars ⇒ identical to current behaviour.

### 15.2 `/docs` & `/openapi.json` (production recommendation)

Preflight confirmed both return `200` anonymously on production. Recommended
change (batch with other release changes; **not applied here**):

```diff
--- a/backend/app/main.py
+++ b/backend/app/main.py
@@
 def create_app() -> FastAPI:
+    _expose_docs = (app_settings.app_env or "").strip().lower() != "production"
     app = FastAPI(
         title="Faculty Patent Collection Portal",
         version="0.1.0",
         description=(
             "Production-grade, free-first institutional web portal "
             "for patents and design registrations"
         ),
-        docs_url="/docs",
-        redoc_url="/redoc",
+        docs_url="/docs" if _expose_docs else None,
+        redoc_url="/redoc" if _expose_docs else None,
+        openapi_url="/openapi.json" if _expose_docs else None,
         lifespan=lifespan_scheduler,
     )
```

Notes: gating on `production` (not `staging`) keeps the API browsable on staging
for QA; FastAPI treats `None` as "disabled". No secrets are currently embedded in
the schema.

### 15.3 Optional staging blueprint `render.staging.yaml` (new file, not created)

A **separate** file (so the production `render.yaml` is untouched; Render only
auto-reads `render.yaml` unless another file is explicitly selected):

```yaml
services:
  - type: web
    name: faculty-portal-api-staging
    runtime: docker
    dockerfilePath: ./Dockerfile
    dockerContext: .
    plan: free
    region: singapore
    healthCheckPath: /healthz
    autoDeploy: false
    preDeployCommand: alembic -c /app/alembic.ini upgrade head
    envVars:
      - key: APP_ENV
        value: staging
      - key: DATABASE_URL
        sync: false          # paste the STAGING database DSN in the dashboard
      - key: SECRET_KEY
        generateValue: true
      - key: CORS_ORIGINS
        sync: false          # set to the staging Pages origin
      - key: COOKIE_SECURE
        value: "true"
      - key: COOKIE_SAMESITE
        value: none
      - key: LOCAL_STORAGE_ROOT
        value: /data/storage
```

No secret values are stored in the file. Creating this file is a repo change and
requires approval; it does **not** affect the production service.

---

## 16. What was verified locally this phase

* `scripts/staging/test_guard.py` — **19/19 passed** (pure logic, no DB).
* DB-guard CLI matrix (§5.1) — every row matches the table.
* Playwright guard self-checks — **7/7 passed** with a hosted-style allowlist;
  production host aborts config load (exit 1).
* No local database was written; no hosted system was contacted.

### Phase 2C additions (investigation only)

* `docs/STAGING_PROVISIONING_INVESTIGATION.md` — **new**: verified provider
  findings (with citations), Path A vs C, and the recommended path.
* §5.3 and §11 above — updated from *unverified* to **verified** Render
  capabilities/costs.
* Re-ran `scripts/staging/test_guard.py` → **19 passed** (§8 of the investigation
  doc); confirmed no fallback to `DATABASE_URL` and that `.env` is not in the
  image. No remote action, no resource created, no guard change.
