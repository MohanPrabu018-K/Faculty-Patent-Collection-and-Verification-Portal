# Production Deployment Runbook

**Environment:** Render Free Web Service (Backend) & Cloudflare Pages (Frontend)  
**Maintained by:** Agent 10 (DevOps & Deployment Engineer)

---

## 1. Environment Variables Configuration

Set these variables in the **Render Dashboard** (`faculty-portal-api` -> **Environment**):

```ini
APP_ENV=production
DEBUG=false
COOKIE_SECURE=true
COOKIE_SAMESITE=none
WEB_CONCURRENCY=2
LOCAL_STORAGE_ROOT=/data/storage
STORAGE_BACKEND=gdrive
GOOGLE_DRIVE_FOLDER_ID=<your_google_drive_folder_id>
GOOGLE_DRIVE_CLIENT_ID=<your_google_cloud_client_id>
GOOGLE_DRIVE_CLIENT_SECRET=<your_google_cloud_client_secret>
GOOGLE_DRIVE_REFRESH_TOKEN=<your_oauth_refresh_token>
DATABASE_URL=postgresql+asyncpg://<neon_user>:<neon_password>@<neon_host>/neondb?sslmode=require
CORS_ORIGINS=https://faculty-patent-collection-and-verification-portal.pages.dev
JWT_ACCESS_TOKEN_MINUTES=30
```

---

## 2. Deployment Sequence

1. **Database Migrations:**
   * Handled automatically by the Render build via `preDeployCommand: "alembic -c /app/alembic.ini upgrade head"`.
2. **Backend Deployment:**
   * Render automatically triggers a Docker build when new commits land on `main` (or click **Manual Deploy** -> **Deploy latest commit**).
3. **Frontend Deployment:**
   * Cloudflare Pages connects to the GitHub repository and deploys automatically upon push to `main`.
   * Build command: `npm run build`
   * Build output directory: `frontend/dist`
   * Root directory: `frontend`
4. **Health Verification:**
   ```bash
   curl -s https://faculty-patent-portal-api.onrender.com/healthz
   # Expected: {"status":"ok"}
   curl -s https://faculty-patent-portal-api.onrender.com/readyz
   # Expected: {"status":"ready"}
   ```

---

## 3. Rollback Procedure

If a production incident occurs:
1. **Backend Rollback:**
   * In Render Dashboard: **Deploys** -> Select the previous successful deploy -> Click **Rollback to this deploy**.
2. **Frontend Rollback:**
   * In Cloudflare Pages: **Deployments** -> Select previous deployment -> Click **Rollback**.
3. **Database Rollback:**
   * `alembic -c alembic.ini downgrade -1` from the Render service shell if a migration was problematic.
