# Faculty Patent Collection & Verification Portal (FPP)
## Project Overview & Autonomous Team Structure

**Product Owner / Client:** Client  
**Team Structure:** Autonomous Multidisciplinary Software Engineering Organization (Agents 1–13)  
**Budget Constraint:** **Strict ₹0.00 (Zero Cost)** — No paid subscriptions, no credit card activations, no paid hosting/API upgrades.  
**Repository:** [https://github.com/MohanPrabu018-K/Faculty-Patent-Collection-and-Verification-Portal](https://github.com/MohanPrabu018-K/Faculty-Patent-Collection-and-Verification-Portal)  
**Authoritative Branch:** `main` (Commit: `8ae07e3`)  
**Live Production Deployments:**
* **Frontend:** Cloudflare Pages — [https://faculty-patent-collection-and-verification-portal.pages.dev](https://faculty-patent-collection-and-verification-portal.pages.dev/)
* **Backend:** Render Web Service (Free Tier) — [https://faculty-patent-portal-api.onrender.com](https://faculty-patent-portal-api.onrender.com)
  * Public Health Endpoint: `/healthz` (Status: `{"status":"ok"}`)
  * Readiness Endpoint: `/readyz` (Status: `{"status":"ready"}`)
* **Database:** Neon PostgreSQL 16 (TLS required, pooled)
* **Persistent Document Storage:** Google Drive API v3 (15 GB ₹0 personal storage tier via OAuth 2.0 User Credentials) + Local fallback

---

## Autonomous Team Organization

| Agent ID | Specialized Role | Core Responsibilities in FPP |
|---|---|---|
| **Agent 1** | **Project Director / Team Lead** | Owns master delivery plan, resolves conflicts, enforces QA gates, ensures zero-cost compliance. |
| **Agent 2** | **Business Analyst / Requirements Engineer** | Maps roles (Faculty, HOD, Super Admin), verifies traceability matrix, validates business logic. |
| **Agent 3** | **UI/UX Designer** | Optimizes responsive layouts, accessibility, error messaging, visual hierarchy, mobile/desktop consistency. |
| **Agent 4** | **Frontend Developer** | Owns React 19 + TypeScript + Vite SPA, UI state, API error handling, Vitest regression suite. |
| **Agent 5** | **Backend Developer** | Owns FastAPI endpoints, 11-agent document processing pipeline, SQLAlchemy models, Alembic migrations. |
| **Agent 6** | **Database & Storage Engineer** | PostgreSQL schema integrity, indexes, foreign keys, Google Drive API persistence, container wipe recovery. |
| **Agent 7** | **OCR & Pipeline Engineer** | PyMuPDF, PaddleOCR, Tesseract, extraction accuracy, background tasks, stuck job recovery. |
| **Agent 8** | **QA & Test Automation Engineer** | Manages test strategy, unit/integration/API suites, browser automation, negative & boundary test cases. |
| **Agent 9** | **Security Engineer** | Role-based access control, CSRF validation, SameSite/Secure cookies, secret leak audits, path traversal defense. |
| **Agent 10** | **DevOps & Deployment Engineer** | Cloudflare Pages, Render Free container builds, health checks, environment variables, cold-start handling. |
| **Agent 11** | **Git & Release Engineer** | Branch safety, non-destructive commits, changelogs, release tagging, upstream synchronization. |
| **Agent 12** | **Free-Infrastructure Researcher** | Evaluates ₹0 cloud quotas, eliminates hidden costs or credit card traps, verifies free-tier constraints. |
| **Agent 13** | **Final Acceptance & Release Manager** | Aggregates workstream evidence, audits definition of done, prepares verified client handoff. |
