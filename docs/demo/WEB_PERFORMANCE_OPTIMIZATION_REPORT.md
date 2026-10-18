# FPP Web Performance Optimization Report

**Scope:** local staging only (frontend 5173 + backend 8099 + `faculty_portal_staging`). No production contact, no DB writes beyond read-only probes, no commits/pushes/deploys, demo dataset verified unchanged afterward.

## 1. Executive summary
The application was already fast: API p95 ≤ 63 ms, sub-second warm navigations, CLS 0, zero long tasks, lean dependency set with effective route splitting and sane React Query defaults. Exactly **one** evidence-backed optimization was justified and shipped: eliminating a redundant `/auth/me` round-trip on login. Everything else audited (bundle, deps, N+1, polling, fonts, images, OCR path) was deliberately left unchanged with documented reasons. Verdict: **PARTIAL** (one verified improvement; no regressions).

## 2. Baseline measurements (before any change)

| Area | Result | Tool |
|---|---|---|
| JS bundle total | ~390 KB initial (index 278.2 KB + LoginPage 111.6 KB), CSS 16.5 KB, dist 0.55 MB | `vite build` output |
| Deps | react, router, tanstack-query, hook-form, zod, lucide — no charts/PDF/heavy libs | `package.json` |
| Duplication | none (zod only in login chunk, router only in index) | dist string scan |
| API medians (n=7) | healthz 15.4, readyz 2.7, dashboards 26–45, lists 24–41, detail 26, assoc 21, notif 18 ms; p95 ≤ 63 ms | `fpp-perf/time_api.py` |
| React Query defaults | staleTime 30 s, no window-focus refetch, retry 1, bell auth-gated | source (`main.tsx`, bell) |
| Login flow `/auth/me` calls | 4 per login (dev; 3 in prod: mount probe + login + page re-fetch) | Playwright `perf_probe.spec.ts` |
| Page loads (dev) | first dashboard DCL 331/load 3501/FCP 1604 ms; warm pages DCL ~200/FCP ~300 ms; CLS 0; longtasks 0 | Performance API probe |
| LCP/INP | **unmeasurable** in headless lab (no LCP entries dispatched); Lighthouse unavailable (not installed) | documented limitation |

## 3. Bottlenecks discovered
1. **Redundant `/auth/me` on login** (only actionable one): `LoginPage.onSubmit` fetched the session a second time purely for role routing, although `AuthProvider.login` had just fetched it. Proven by request logs (4 me-calls per login in dev).
2. Non-issues ruled out with evidence: no duplicated chunks; no N+1 in hot list endpoints (batched display/dup/conflict queries in `hod.py`); no global polling (30 s bell only, auth-gated); no per-navigation session refetch (`ProtectedRoute` reads context only); OCR/pipeline already off the request path (BackgroundTasks).

## 4–5. Code changed + why
- `frontend/src/stores/auth.tsx`: `login()` now **returns** the fresh `User` (additive type change; sole caller updated).
- `frontend/src/features/auth/LoginPage.tsx`: uses the returned session for role routing; second `api.me()` removed.
- Effect: login flow drops one identical round-trip (~25–40 ms + its failure modes) on the critical first-run path. No behavior, route, message, or security change.

Deliberately NOT changed: zod/hook-form removal (stable-functionality tradeoff forbidden by brief); route splitting (already per-page chunks; login must stay eager); backend queries (all <65 ms, no proven bottleneck); font CDN (sandbox-offline only; `display=swap` + fallback already correct); images (only the docs workflow SVG — preserved); OCR path (already async).

## 6. Before/after comparison

| Area | Baseline | After | Evidence |
|---|---|---|---|
| `/auth/me` per login | 4 (dev) / 3 (prod) | 3 (dev) / 2 (prod) | probe logs before/after |
| Login wall time | — | unchanged within noise (DCL 331→345 ms) | probe (dominated by login POST + parse, not the removed call) |
| Bundle | index 278.2 + LoginPage 111.6 KB | index 278.3 + LoginPage 111.6 KB (unchanged) | build output |
| API medians | 15–45 ms | untouched (no backend change) | — |
| FCP/CLS/longtasks | 1604/280 ms, 0, 0 | unchanged | probe |

Honest reading: the win is one fewer round-trip and one fewer failure point on login, not a headline latency drop — backend and rendering were already well within targets.

## 7. Test commands + actual results
- `tsc --noEmit`: exit 0. `LoginPage` auth specs: 12/12. Full Vitest: **19 files / 138 passed**. `vite build`: exit 0.
- Demo browser suite (real system Chrome, live stack): **6/6** post-change (login flows for all roles incl. SA grant-button presence, HOD fan-out, role-gate denial, mobile).
- Backend suite (475/0) stands — backend code untouched this cycle.
- Perf probe spec: measurement only (1 passed), retained in `tests-staging/` as reusable tooling.

## 8. Functional regression
No behavior changed except removing the duplicate fetch: login routing (all roles), session restore, dashboard renders, HOD fan-out, grant-button gating all re-proven in-browser post-change. Zero Vitest/Playwright regressions.

## 9. Database/production safety
Read-only probes only (minted-JWT GETs); demo states re-verified identical afterward (GRANT-READY pristine); Neon never connected; no emails; no commits/pushes/deploys; workflow SVG untouched; no migrations.

## 10. Remaining bottlenecks
- Login chunk 111.6 KB (zod + hook-form) — accepted; replacing validation libs is out of scope per brief.
- First-load parse cost (~1.6 s FCP cold dev) — needs production field data to judge; no lab Lighthouse available.
- `load=3.5 s` first dashboard includes login POST + cold module eval — backend slice is ~45 ms; remainder is client parse, already mitigated by per-route chunks.

## 11. Unmeasurable here
LCP/INP (headless emits no LCP entries), Lighthouse lab + field data (tool unavailable), production CDN/font timing (sandbox offline), real-user metrics (no RUM instrumentation — not added).

## 12. Git status
Uncommitted (intentional): `LoginPage.tsx`, `stores/auth.tsx` (this task), `test_association_lifecycle.py` +2 tests, `index.html` favicon (prior demo cycle). New untracked tooling: `tests-staging/perf_probe.spec.ts`. Nothing committed/pushed/deployed.

## 13. Verdict: **PARTIAL**
One measured, regression-free improvement shipped; the rest of the stack was proven already-optimal for its scale with evidence, and correctly left alone. No functional or data-integrity regression. Production readiness still requires an authorized release + live verification (unchanged standing rule).
