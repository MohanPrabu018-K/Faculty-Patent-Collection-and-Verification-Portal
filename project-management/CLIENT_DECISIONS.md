# Client Decisions & Authorization Log

**Product Owner / Client:** Client  
**Budget Boundary:** Strict ₹0.00 (Zero Billing Activation)

---

## Decision History & Record

### 1. Document Storage Provider Selection
* **Context:** Document storage on Render's free tier is ephemeral. A persistent cloud storage provider was required to prevent document loss upon container redeployment or idle spin-down.
* **Client Decision:** Selected **Google Drive API** as the persistent document storage provider.
* **Constraint:** Strict ₹0 budget; must not require Google Workspace paid plan, paid storage upgrade, or credit card details.
* **Resolution:** Verified that Google Drive API can be configured completely free with a standard personal `@gmail.com` account via OAuth 2.0 User Credentials + Refresh Token (15 GB free storage). Implemented and verified in commit `8ae07e3`.

### 2. Git Branch Consolidation & Preservation
* **Context:** Several feature and fix branches existed (`fix/pipeline-recovery-and-design-dates`, `baru`, `main`).
* **Client Decision:** Approved consolidating verified fixes into `main` while strictly preserving branch history and avoiding force-pushes.
* **Resolution:** All 6 key bug fixes merged, tested, and pushed to `origin/main`. `origin/baru` preserved.

---

## Pending Client Action Required (Production Storage Activation)

To activate Google Drive persistent storage in your live Render backend, follow these 3 steps:

1. **Google Cloud Console (No credit card / ₹0):**
   * Create a project in [Google Cloud Console](https://console.cloud.google.com/).
   * Enable the **Google Drive API**.
   * Configure **OAuth consent screen** (External, add your email under Test Users, scope: `https://www.googleapis.com/auth/drive.file`).
   * Create **OAuth Client ID** (Type: **Desktop app**).
2. **Run Local Token Generator:**
   ```powershell
   backend\.venv\Scripts\python scripts/setup_google_drive.py
   ```
   Log into your `@gmail.com` account in the browser when prompted. The script will output your Refresh Token and Folder ID.
3. **Add Environment Variables to Render Dashboard:**
   Add `STORAGE_BACKEND=gdrive`, `GOOGLE_DRIVE_FOLDER_ID`, `GOOGLE_DRIVE_CLIENT_ID`, `GOOGLE_DRIVE_CLIENT_SECRET`, and `GOOGLE_DRIVE_REFRESH_TOKEN` to your backend service on Render.
