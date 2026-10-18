# Staging environment & authenticated E2E setup

> Status: **proposal + local tooling.** Nothing in this document has been
> applied to Render, Cloudflare, Vercel or any hosted account. All remote steps
> require explicit owner approval before execution.

This is the Phase 2A deliverable for release QA. Its purpose is to make the
authenticated rule-document test matrix (rules A–F) runnable **without touching
production**.

## 1. Why a separate staging stack

| Risk | Mitigation |
| --- | --- |
| Authenticated tests write rows (associations, grants, audit) | Run against a **separate DB** that never holds production data |
| Production `DATABASE_URL` (Neon) is the default in the repo `.env` | Staging tooling reads **only** `STAGING_DATABASE_URL`; fail-closed guard refuses production hosts |
| Frontend/backend version skew (backend commit unknown) | Staging deploys a known commit so QA results are attributable |
| Creating real users on production | Provision **synthetic** `@staging.example.com` accounts on staging only |

## 2. Target architecture

```
                 VITE_API_BASE_URL
 Browser ──► Staging frontend ────────────────────► Staging backend (FastAPI)
             (Static Site / local vite)             (Render web service OR local uvicorn)
                                                          │  DATABASE_URL
                                                          ▼
                                                    Staging PostgreSQL
                                                    (Render/Neon *branch* or local docker)
```

Two supported profiles:

* **A. Fully local (recommended for this phase).** Local Postgres + local
  `uvicorn` + local `vite`. No hosted resources, no approvals needed. This is
  what the tooling defaults to and what is executed in Phase 2A.
* **B. Hosted staging.** A second Render web service + a separate staging
  Postgres branch + a second Static Site. Requires owner approval (section 6).

## 3. Environment variables

### 3.1 Staging backend

For the **hosted** profile (`APP_ENV=staging`), note that `APP_ENV=staging` is
treated as production by `backend/app/core/config.py` (`_PROD_ENVS`) **on
purpose** — it keeps every production safety guard switched on (no debug
secret, secure cookies, non-localhost DB, CORS required), so staging is a
faithful pre-flight for production. That guard also refuses a `localhost`
`DATABASE_URL`, so a hosted staging backend cannot accidentally use a local DB.

The **local** profile therefore uses `APP_ENV=development` (the guard above
would reject the local DB). Everything else is identical.

| Variable | Hosted staging (`APP_ENV=staging`) | Local profile (`APP_ENV=development`) |
| --- | --- | --- |
| `APP_ENV` | `staging` | `development` |
| `DATABASE_URL` | staging DB DSN (non-local) | `…127.0.0.1:5432/faculty_portal_staging` |
| `SECRET_KEY` | fresh, random ≥ 32 chars | any ≥ 32 chars (still enforced) |
| `CORS_ORIGINS` | staging frontend origin (https, exact) | `http://localhost:5173` |
| `COOKIE_SECURE` | `true` | `false` |
| `COOKIE_SAMESITE` | `none` (frontend and API are different sites) | `lax` |
| `E2E_TEST` | `1` (widen login rate limit — see caution) | `1` |
| `OCRSPACE_API_KEY` | unset (offline OCR) | unset |
| `LOCAL_STORAGE_ROOT` | tmp dir | local dir |

> **`COOKIE_SAMESITE=none` is required for the hosted profile.** `POST
> /api/v1/auth/refresh` reads the `access_token` **cookie**, and a HIPAA-style
> cross-origin deploy (staging frontend on `*.pages.dev`, API on
> `*.onrender.com`) only sends it when the cookie is `SameSite=None; Secure` —
> exactly what production's `render.yaml` sets. Omitting it makes session
> refresh silently fail across reloads.

> **Caution — `E2E_TEST=1` multiplies rate limits ×10000** (`app/api/auth.py`,
> `app/core/security_middleware.py`). That removes brute-force protection, so a
> hosted staging API must be **non-production and disposable**, and should be
> gated (Cloudflare Access / IP allow-list) or torn down promptly. If that is
> not acceptable, leave `E2E_TEST` unset and raise the login rate limit only.

### 3.2 Staging frontend

`VITE_API_BASE_URL` is baked in at build time (no runtime config).

```
VITE_API_BASE_URL=http://localhost:8000/api/v1     # local profile
# or https://<staging-api-host>/api/v1              # hosted profile
```

### 3.3 Staging tooling (host-only, never deployed)

| Variable | Purpose |
| --- | --- |
| `STAGING_DATABASE_URL` | the **only** DB URL the staging scripts read |
| `STAGING_ALLOW_REMOTE_DB` | must be `1` to allow a non-loopback DB host |
| `STAGING_DB_HOST_ALLOWLIST` | comma-separated hosts explicitly acknowledged as staging |
| `STAGING_CONFIRM` | must be `1` to make the Playwright staging project run |
| `STAGING_FRONTEND_URL` | the staging frontend under test |
| `STAGING_API_URL` | the staging API under test |
| `STAGING_ALLOWED_HOSTS` | comma-separated hostnames the Playwright guard may drive (required for any non-loopback host) |

All three staging secrets/values files are gitignored (see section 7).

## 4. Fail-closed guards

### 4.1 Database guard (`scripts/staging/guard.py`)

Used by `provision_staging.py`, `teardown_staging.py`, and (optionally) by the
pytest suite. Rules, in order:

1. Loopback (`127.0.0.1`, `localhost`, `::1`) → allowed.
2. Host matches a production/managed marker (`neon.tech`, `onrender.com`,
   `render.com`, `supabase.co`, `amazonaws.com`, …) → **always refused**, even
   with `STAGING_ALLOW_REMOTE_DB=1`. There is no override.
3. Any other remote host → requires `STAGING_ALLOW_REMOTE_DB=1` **and** the host
   in `STAGING_DB_HOST_ALLOWLIST`.
4. Database name must look disposable (`staging`/`test`/…) unless loopback, and
   must not be a reserved production name (`neondb`, `faculty_portal`, …).

`STAGING_DATABASE_URL` never falls back to the application `DATABASE_URL`, so a
leftover production env cannot make the tooling target production.

**Hosted-provider consequence (important).** Because rule 2 refuses the managed
providers this repo actually uses, the Python tooling **cannot target a
Render/Neon/Supabase Postgres over its public hostname**, even with the opt-in
and allowlist set. That is deliberate and verified: the allowlist can *never* be
configured to reach production (see `docs/STAGING_HOSTED_PLAN.md` §5 and
`scripts/staging/test_guard.py`). The practical effect is that hosted
provisioning must run against either the provider's **internal** hostname (no
public domain) or a staging DB whose hostname is not on the marker list.

**Known limitation.** `DISPOSABLE_DB_MARKERS` includes the two-character token
`ci` (and the broad token `stage`), so the "looks disposable" name check is
looser than its name suggests (a name that merely contains "ci" passes). The
host checks and the reserved-name checks still apply, so this is a hardening
item rather than a production-leak vector. It is pinned by a test in
`scripts/staging/test_guard.py` so tightening it later is a visible change.

Reuse with pytest: the existing `backend/tests/conftest.py` guard already aborts
unless `DATABASE_URL` is a local host (opt-in `ALLOW_REMOTE_TEST_DB=1`). Run the
suite with `DATABASE_URL` pointed at the disposable staging DB.

### 4.2 Playwright guard (`frontend/tests-staging/guard.ts`)

The staging project refuses to run unless:

1. `STAGING_CONFIRM=1` (explicit human acknowledgement), **and**
2. `STAGING_FRONTEND_URL` and `STAGING_API_URL` are both set, **and**
3. neither URL host is one of the two **exact** known production hosts
   (`faculty-patent-collection-and-verification-portal.pages.dev`,
   `faculty-patent-portal-api.onrender.com`) — those are refused even if
   allow-listed — **and**
4. every non-loopback host appears in `STAGING_ALLOWED_HOSTS` (comma-separated).

**This differs from the DB guard on purpose.** The Playwright guard uses an
*exact* production deny-list plus an allowlist, so it **can** drive a hosted
staging frontend/API (e.g. `faculty-portal-staging.pages.dev` +
`faculty-portal-api-staging.onrender.com`) once those hosts are allow-listed —
verified locally (7/7 guard self-checks pass with a hosted-style allowlist, and
config load aborts on the production host). The DB guard, by contrast, refuses
whole managed-cloud providers and therefore cannot target a Render/Neon staging
Postgres over its public hostname.

The config deliberately has **no `webServer`**: the operator starts the
environment explicitly, so the suite can never silently boot a server against
the wrong DB.

## 5. Provisioning & teardown (reproducible)

```powershell
# local disposable DB (name must contain "staging"/"test")
$env:STAGING_DATABASE_URL = 'postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/faculty_portal_staging'

python scripts/staging/provision_staging.py --create-database --migrate
#   -> creates DB if needed, runs alembic upgrade head, seeds departments,
#      designations, 15 synthetic accounts and the scenario records,
#      writes frontend/tests-staging/.staging-fixtures.json

python scripts/staging/teardown_staging.py          # dry-run report
python scripts/staging/teardown_staging.py --yes    # delete only stg- rows
```

Both scripts are idempotent and delete/modify **only** rows whose id starts with
`stg-`. See `STAGING_TEST_DATA.md` for the account/record matrix.

## 6. Hosted staging (requires approval — not executed)

The full, guard-aware runbook lives in `docs/STAGING_HOSTED_PLAN.md`. Summary:

1. Create a **new** Render web service `faculty-portal-api-staging` from this
   repo (not a redeploy of production), `autoDeploy: false`, same Dockerfile,
   pinned to the approved commit (`8503fe54…`).
2. Create a **separate** staging Postgres. **Do not reuse the production
   database/branch.** Note the DB guard: the tooling cannot target Render/Neon/
   Supabase over a **public** hostname (§4.1), so pick a provisioning path from
   `STAGING_HOSTED_PLAN.md` §5.
3. Set the staging backend env vars from §3.1 (including `COOKIE_SAMESITE=none`).
4. Create a **separate** Static Site / Pages project with `VITE_API_BASE_URL`
   from §3.2, then add its host and the API host to `STAGING_ALLOWED_HOSTS`.
5. Deploy the pinned commit; `alembic upgrade head` runs as the
   `preDeployCommand`, then run `provision_staging.py` (omit `--create-database`
   for managed DBs — see the plan).

No step here has been performed.

## 7. Gitignored artifacts

Added to `.gitignore`:

```
/scripts/staging/staging_accounts.local.json
/scripts/staging/staging_accounts.json
/scripts/staging/*.env
/scripts/staging/hosted.env
/frontend/tests-staging/.env
/frontend/tests-staging/.staging-fixtures.json
/frontend/tests-staging/.auth/
/frontend/test-results-staging/
/frontend/playwright-report-staging/
```

## 8. `/docs` and `/openapi.json` exposure (recommendation only)

Live preflight confirmed that `https://<prod-api>/docs` and `/openapi.json`
return `200` anonymously — the full API surface is publicly enumerable. This is
**not** changed by this document.

Recommendation (apply only with approval, and only alongside the other release
changes):

* In `backend/app/main.py`, gate the docs URLs by environment, e.g.
  `docs_url="/docs" if app_settings.app_env != "production" else None` and the
  same for `redoc_url` / `openapi_url`; or
* Put the API behind Cloudflare Access / an `X-Admin` gate for `/docs*` and
  `/openapi.json`.
* If the endpoints stay public, accept that the schema is discoverable and
  ensure no secrets are ever embedded in it (currently none are).

## 9. Running the authenticated staging suite

```powershell
$env:STAGING_CONFIRM='1'
$env:STAGING_FRONTEND_URL='http://localhost:5173'
$env:STAGING_API_URL='http://localhost:8000'
# start the local stack first (uvicorn + vite) -- the config will NOT do it
cd frontend
npx playwright test -c playwright-staging.config.ts
```

See `frontend/tests-staging/README.md` for the scenario matrix and how it maps
to the rules A–F.
