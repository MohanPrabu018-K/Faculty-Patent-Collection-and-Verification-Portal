# Staging DB Provisioning Investigation (Phase 2C — findings only)

**Status:** investigation complete. **No remote resource was created, no configuration
was changed, no guard was weakened, no production data/config was accessed, and
nothing was committed or deployed.** This document records only what was verified
from **official provider documentation**, plus a recommended safe provisioning path
and the smallest next action.

Related: `docs/STAGING_HOSTED_PLAN.md` (§5 blocker, §15 proposed diffs),
`docs/STAGING_SETUP.md`, `scripts/staging/guard.py`, `scripts/staging/test_guard.py`.

---

## 1. The blocker being resolved

`scripts/staging/guard.py` refuses any host containing a managed-cloud marker
**before** the allowlist is even consulted:

```python
PRODUCTION_HOST_MARKERS = ("neon.tech", "onrender.com", "render.com",
                           "supabase.co", "supabase.com", "amazonaws.com",
                           "azure.com", "rds.amazonaws.com")
```

The repo's intended hosted providers — Render Postgres and Neon — both match that
list, so neither is reachable from the operator machine over its **public**
hostname, even with `STAGING_ALLOW_REMOTE_DB=1` + an exact allowlist. Two ways out:
run provisioning **inside** the provider network against a non-marker hostname
(Path A), or point at a staging database whose **hostname itself** is not on the
marker list (Path C). Path B (a guard extension) remains documented but
unapproved and **not applied**.

---

## 2. Verified Render capabilities (official docs)

Everything below is quoted/derived from Render's own documentation (links in §9).

### 2.1 Postgres connectivity
* Every Render Postgres has **two URLs**: an **internal URL** for other Render
  services **in the same region**, and an **external URL** for "everything else".
  External connections traverse the public internet; internal connections stay on
  the private network. *(Render: Connect to Render Postgres)*
* **TLS:** external connections use a Render-managed certificate. Internal
  connections **do not support** `sslmode=verify-ca` / `verify-full`; use
  `sslmode=require` to require TLS and prevent plaintext fallback. *(same page)*
* **External access can be fully disabled** for a database with
  `--clear-ip-allow-list` (CLI) / `ipAllowList` (API/Blueprint), leaving
  **internal-only** access. *(same page)*
* Backing this: `GET /v1/postgres/{id}/connection-info` returns both
  `internalConnectionString` and `externalConnectionString`. *(Render Public API)*
* **Inbound IP rules on individual Render Postgres / Key Value datastores are
  available to *all* workspaces** (Hobby included) — i.e. an IP allow-list is
  possible on Render Postgres even on Hobby. It is **IP-based only**.
  *(Render: Inbound IP rules; Pricing feature table)*

### 2.2 In-network execution (this is what Path A needs)
* **Shell / SSH requires a *paid* web service:**
  | Service type | Dashboard shell | SSH |
  | --- | --- | --- |
  | Paid web service | 🟢 | 🟢 |
  | Free web service | ❌ | ❌ |
  *(Render: SSH / Shell access)*
* **Free web services cannot run one-off jobs** (among other paid-only features:
  scaling, persistent disks, edge caching). *(Render: Free instances — "Other limitations")*
* **One-off jobs** reuse a base service's **build artifact and environment
  variables**, are created via the API (`startCommand`), and are **billed
  per-second** while running. *(Render: One-off jobs)*
* **`initialDeployHook`** (Blueprint field) runs **once**, after a service's first
  successful deploy, for "one-time initialization tasks such as **seeding a
  database**"; it is available for **web services, private services, and
  background workers**. No plan restriction is stated. `afterFirstDeployCommand`
  is its deprecated alias. *(Render: Blueprint YAML Reference)*
* `preDeployCommand` runs **before every deploy** (this is what production
  `render.yaml` already uses for migrations). *(same page)*

### 2.3 Plan entitlements / costs (verified on the pricing page)
| Item | Free | Cheapest paid |
| --- | --- | --- |
| Hobby workspace | **$0/mo** + compute | Pro **$25/mo** (+ compute) |
| Web service compute | Free plan **$0/mo** (512 MB, <1 CPU) | **$7/mo** (`0.5c-512mb`, 512 MB, 1 CPU); `1c-2g` = **$25/mo** |
| Postgres compute | Free plan **$0/mo** (256 MB, 100 connections) | **$6/mo** (`0.1c-256mb`); `0.5c-1g` = **$19/mo** |
| Dedicated outbound IPs | ✗ | **Pro workspace or higher + an additional monthly fee** |
| Inbound IP rules (datastores) | ✓ (all workspaces) | ✓ |
| Inbound IP rules (web services / entire env) | ✗ | Scale/Enterprise only |

*(Render: Pricing; Compute plans; Platform features by plan)*

### 2.4 Free Postgres hard limits (verified)
* **Only one Free Render Postgres may be active per workspace.**
* **1 GB** storage fixed.
* **Expires 30 days after creation**; a **14-day grace** to upgrade, after which
  Render **deletes the database and all of its data**.
*(Render: Free instances — "Free Postgres")*

### 2.5 Private networking nuance
* Free web services **can send** private-network requests to datastores/paid
  services in the same region, but **cannot receive** private-network traffic.
*(Render: Private Network; Free instances)*

---

## 3. Path A — in-network provisioning (guard unchanged)

**Idea:** run `provision_staging.py` from inside Render against the DB's
**internal** hostname (`dpg-…`, which contains no marker), with
`STAGING_ALLOW_REMOTE_DB=1` + `STAGING_DB_HOST_ALLOWLIST=<internal host>`.

**Verified prerequisites and blockers:**

1. **A paid web service compute plan is required** for Shell/one-off jobs
   (§2.2). Cheapest verified: **$7/mo** (`0.5c-512mb`). The staging blueprint
   in the plan currently says `plan: free` — **inconsistent with Path A**.
   *Alternative:* the one-time **`initialDeployHook`** is documented for web
   services without a stated plan restriction, so it *may* work on a free
   service — but it runs **only once per service instance**, so it cannot
   re-provision or run teardown.
2. **`scripts/` is not in the image.** The `Dockerfile` copies only `backend/`
   and `alembic.ini` (WORKDIR `/app/backend`). Path A therefore needs a
   `COPY scripts/ …` (or a raw.githubusercontent pointer / backend-side seed
   entrypoint). *(repo `Dockerfile`)*
3. **Credential / fixture retrieval is the killer.** Provisioning **generates
   random passwords on the machine that runs it** and writes two git-ignored
   files *next to the script*:
   * `scripts/staging/staging_accounts.local.json` (`RESOLVED_ACCOUNTS_PATH`)
   * `frontend/tests-staging/.staging-fixtures.json` (`FIXTURES_PATH`)

   Run **inside a container**, both land on the **ephemeral container filesystem**
   and are lost; the Playwright suite runs on the operator machine and reads
   `.staging-fixtures.json` locally. So Path A additionally requires either
   printing fixtures to logs (insecure), or shipping a pre-seeded
   `staging_accounts.local.json` into the image (secrets in an image — undesirable),
   or a **code change** to emit/collect credentials. *(repo `provision_staging.py`)*
4. The internal DB can be made **internal-only** (`ipAllowList: []`) — a genuine
   isolation win — but only the Render network can reach it, reinforcing (1)–(3).

**Net:** Path A buys off-internet isolation but costs a paid plan **plus** a
Dockerfile change **plus** a credential/fixture-retrieval change **plus** one-time-only
seeding (or paid jobs). More moving parts, more code touched.

---

## 4. Path C — non-marker staging database (guard unchanged)

**Idea:** keep the exact tested local provisioning flow, but point
`STAGING_DATABASE_URL` at a database whose **hostname is not on the marker list**.

### 4.1 Exact guard requirements for a passing URL
A `STAGING_DATABASE_URL` is accepted iff **all** hold (`scripts/staging/guard.py`):

1. Scheme ∈ `{postgresql, postgresql+asyncpg, postgresql+psycopg2, postgres}`.
2. Host contains **none of**: `neon.tech`, `onrender.com`, `render.com`,
   `supabase.co`, `supabase.com`, `amazonaws.com`, `azure.com`,
   `rds.amazonaws.com`.
3. `STAGING_ALLOW_REMOTE_DB=1` **and** the host is listed **exactly** in
   `STAGING_DB_HOST_ALLOWLIST` (comma-separated).
4. DB name is **not** exactly one of `{neondb, faculty_portal, production, prod, postgres}`.
5. DB name contains at least one of `{staging, stage, test, ci, disposable, scratch}`.

> Recommendation (hardening): choose an **unambiguous** DB name such as
> `faculty_portal_staging`. Avoid names that pass only via the loose `ci`/`stage`
> substrings (e.g. `citadel` contains `ci`) — those are the documented hardening
> items in `docs/STAGING_SETUP.md`.

### 4.2 Candidate provider classes (isolation verified from their docs)
No provider below is selected or created; only the *facts* are verified.

* **DigitalOcean Managed PostgreSQL** — exposes cluster **hostname/port/
  credentials/TLS** via Control Panel/API/CLI, encrypts in transit with TLS
  (`sslmode=require` default; `verify-full` available with a CA), and supports
  **Trusted Sources** (restrict to DO resources and/or external IPs).
  DO does not publish a fixed hostname suffix in the pages reviewed — the exact
  hostname must be taken from the cluster's own connection details and checked
  against §4.1. *(DigitalOcean: Connect; Secure)*

Any self-managed Postgres on a hostname you control (e.g. `staging-db.<domain>`)
also satisfies §4.1 trivially and permits strict IP allow-listing.

### 4.3 Residual risk (be honest about it)
* A Path C database is reachable **over the public internet** (that is *why* the
  guard can reach it). Mitigations: TLS required, strong unique credentials,
  provider firewall/trusted-sources, and a dedicated disposable DB name.
* **Render Hobby has no fixed egress IPs** (dedicated outbound IPs are Pro+ and
  cost extra — §2.3), so you **cannot** cleanly allow-list the *Render backend*
  at the DB firewall on Hobby. You can IP-restrict to the **operator** for
  provisioning, but the deployed staging backend still needs unfiltered (or
  broadly filtered) access.
* This is **no worse than the current production posture**: production already
  uses a publicly-reachable Neon database with TLS + credentials.

### 4.4 Why Path C is reproducible
The provisioning tooling is used **exactly as tested locally** — same guard, same
generation of `staging_accounts.local.json` and `.staging-fixtures.json` on the
operator machine, no image change, no in-container credential handling, no paid
Render compute. The 19-test guard suite and the local 33/33 suite already cover
this code path.

---

## 5. Path comparison

| Criterion | **A. In-network (Render internal)** | **C. Non-marker staging DB (recommended)** |
| --- | --- | --- |
| Guard change | none | none |
| DB exposed to internet | No (`ipAllowList: []`) | Yes (TLS + creds + firewall) — matches production posture |
| Render compute cost | **Paid web service required** for Shell/jobs (~$7/mo+); or one-time `initialDeployHook` | Free web service sufficient |
| Image / code changes | **Dockerfile (`scripts/`) + credential retrieval** | none |
| Provisioning re-runnable | Yes (paid) / **No (one-time hook)** | Yes (local script, idempotent) |
| Fixtures reach operator | **No** without a code change | Yes (as tested) |
| Reproducibility | Lower (more moving parts) | **Highest** (byte-for-byte the tested path) |
| Residual risk | In-container secrets/log handling | Public DB reachability (mitigated) |

**Recommendation: Path C.** It preserves the production safety guarantee
**statically** (no guard change), requires **no** paid Render compute, **no**
image change, and **no** in-container credential surgery, and keeps the exact
provisioning/teardown flow that the 19 guard tests + local suite already prove.
Choose **Path A** only if the owner specifically requires the staging DB to be
off the public internet **and** accepts a paid Render plan + a Dockerfile change +
a credential-retrieval mechanism.

**Smallest next action (one, no remote change):** decide **A vs C**. If **C**,
the next concrete step is for the owner to confirm *which* provider and to read
back **one** staging cluster's connection details (host + DB name) — at that point
§4.1 can be checked against the real hostname; nothing is created before that.
If **A**, the next step is to confirm whether the Render workspace will be on a
**paid compute plan** (needed for Shell/jobs) or whether the one-time
`initialDeployHook` route (with its retrieval caveat) is acceptable.

---

## 6. Review — proposed staging config vs accidental production reuse (item 6)

Reviewed `docs/STAGING_HOSTED_PLAN.md` §15.3 (`render.staging.yaml`) and the
frontend API-base wiring. **No literal secret is present in the proposed file.**

| Concern | Finding |
| --- | --- |
| Reuse of production `SECRET_KEY` | **No** — `generateValue: true` creates a fresh per-service secret. |
| Reuse of production `DATABASE_URL` | **Not in the file** (`sync: false`), but this is a **human-paste risk**: an operator could paste the production Neon DSN. There is **no app-side guard** that refuses a production DB when `APP_ENV=staging` (the fail-closed guard lives only in `scripts/staging/guard.py`). Recommend a follow-up app-side check (e.g. refuse known production DB hosts) — not applied. |
| Reuse of production `CORS_ORIGINS` | Same human-paste risk (`sync: false`); must be the *staging* Pages origin or the staging UI/API pairing breaks. |
| Frontend `VITE_API_BASE_URL` | Must point at the **staging** API (`…-staging.onrender.com/api/v1`). Because it is baked at build time, the mitigation is a **separate Pages project**; verify post-build that the production API host is **absent** from the built bundle. |
| `render.yaml` blast radius | The production `render.yaml` is untouched; the staging file is separate and only read if explicitly selected. A blueprint that names *existing* services would reconfigure them — the staging blueprint must use **new** names. |
| Docker image secrets | The image does **not** include the repo-root `.env` (`.gitignore:8:.env`; Dockerfile copies only `backend/` + `alembic.ini`). Verified locally. |
| `plan: free` | Correct for Path C; **wrong for Path A** (Shell/jobs need a paid plan). |
| `E2E_TEST=1` | Weakens rate limits ×10000 — staging only; tear down promptly. |

## 7. Review — `/docs` & `/openapi.json` hardening diff (item 7)

Reviewed §15.2 independently; **not applied**.

* **Test impact: none found.** No backend test references `/docs`, `/redoc`,
  `openapi.json`, or `docs_url` (only the definitions in `main.py`), and no
  frontend `src` reference exists. The change is safe against the current suite.
* **Mechanics are sound.** `app_settings.app_env` exists; `_expose_docs` is
  computed once in `create_app()`; FastAPI treats `None` as "disabled" for
  `docs_url`/`redoc_url`/`openapi_url`.
* **Behaviour:** production → docs/schema off; staging → on (intended for QA);
  unset `APP_ENV` → defaults to `development` (docs on), acceptable.
* **Nature of the fix:** defense-in-depth / information-disclosure reduction —
  the API surface remains callable; docs exposure is not itself auth bypass.
* Minor alternative: gate on an explicit `ENABLE_DOCS` flag rather than coupling
  to the environment name; the proposed diff is nonetheless minimal and acceptable.

## 8. Verified locally this phase (no DB, no network to any staging system)

* `python -m pytest scripts/staging/test_guard.py -q` → **19 passed** (re-run;
  proves the allowlist cannot reach a production/marker host and that the tooling
  never falls back to `DATABASE_URL`).
* Static confirmation: staging scripts **only set** `os.environ["DATABASE_URL"]`
  *after* resolving `STAGING_DATABASE_URL` (`provision_staging.py:126`,
  `teardown_staging.py:41`); neither reads `DATABASE_URL` for resolution.
* Static confirmation: `.env` is git-ignored and not in the Docker build context.
* No database was written; no hosted system was contacted; nothing committed.

## 9. Sources (official documentation)

* Render — Connect to Render Postgres: https://render.com/docs/postgresql-creating-connecting
* Render — Inbound IP rules: https://render.com/docs/inbound-ip-rules
* Render — SSH / Shell access: https://render.com/docs/ssh
* Render — Free instances: https://render.com/docs/free
* Render — One-off jobs: https://render.com/docs/one-off-jobs
* Render — Blueprint YAML Reference: https://render.com/docs/blueprint-spec
* Render — Private Network: https://render.com/docs/private-network
* Render — Pricing: https://render.com/pricing
* Render — Compute plans: https://render.com/docs/compute-plans
* Render — Platform features by plan: https://render.com/docs/platform-features-by-plan
* Render — Public API (Postgres connection info): https://api-docs.render.com/reference/retrieve-postgres-connection-info
* DigitalOcean — Connect to PostgreSQL: https://docs.digitalocean.com/products/databases/postgresql/how-to/connect/
* DigitalOcean — Secure PostgreSQL (TLS, trusted sources): https://docs.digitalocean.com/products/databases/postgresql/how-to/secure/
