# Zero-Cost Infrastructure Audit & Operational Limits

**Constraint:** Strict ₹0.00 Monthly Operating Budget. No credit cards, no billing activation, no paid upgrades.

---

## 1. Component Evaluation & Audit

| Tier / Component | Provider | Plan & Cost | Usage Limits | Credit Card / Billing Required? | Persistence Guarantee | Cold Start / Sleeping Behavior | Production Recommendation |
|---|---|---|---|---|---|---|---|
| **Frontend Hosting** | **Cloudflare Pages** | Free Tier (₹0) | Unlimited bandwidth, 500 builds/month | **NO** | 100% Edge CDN distribution | Instant (0s) global edge serving | **Keep Cloudflare Pages** |
| **Backend Hosting** | **Render** | Free Web Service (₹0) | 512 MB RAM, 0.1 CPU | **NO** | Ephemeral container disk (`/data/storage` wiped on restart) | Spins down after 15 minutes of inactivity; 50–90s wake-up | **Keep Render Free** (Persistent Google Drive storage protects against disk wipes) |
| **Relational Database** | **Neon PostgreSQL** | Free Tier (₹0) | 0.5 GB storage, PostgreSQL 16 | **NO** | 100% durable hosted PostgreSQL | Transparent connection pooling; awakens within 1-2s | **Keep Neon PostgreSQL** |
| **Document Storage** | **Google Drive API v3** | Personal Google Account (₹0) | 15 GB shared storage per `@gmail.com` account | **NO** (OAuth 2.0 User Credentials) | 100% durable Google cloud storage | O(1) direct download on-demand; no sleeping | **Use Google Drive Storage** (`STORAGE_BACKEND=gdrive`) |
| **Transactional Email** | **Brevo (Sendinblue)** | Free Tier (₹0) | 300 emails / day forever | **NO** | N/A (Transactional API) | Instant API delivery | **Keep Brevo Free** for password resets |
| **Document OCR Engine** | **Local PyMuPDF + Tesseract + PaddleOCR** | Open Source (₹0) | Unlimited local CPU execution | **NO** | N/A (Local container library) | Synchronous / BackgroundTasks pipeline | **Keep Local-First OCR**; optional OCR.Space fallback |

---

## 2. In-Depth Operational Safeguards

### 1. Render Free-Tier Container Wipe Defense
* **Problem:** When Render free instances sleep or redeploy, any files saved in `/data/storage` disappear.
* **FPP Defense:** 
  1. Uploads write to local cache and synchronously upload to your private Google Drive folder.
  2. The Google Drive file ID is persisted in PostgreSQL (`IpFile.storage_key` and `IpRecord.evidence`).
  3. When an authorized user requests a document or background OCR resumes, `get_file_path()` checks if the file exists locally. If missing, it fetches the file directly from Google Drive on-demand and caches it.
  4. In production (`APP_ENV=production`), silent fallback to ephemeral disk is blocked via a fail-fast configuration validator.

### 2. Google Drive Free-Tier Quota vs. Service Account Quota
* **Critical Finding:** Google Cloud Service Accounts have a **0 byte storage quota** by default on personal Google accounts. Uploads into shared folders fail with `403 Storage quota exceeded`.
* **Zero-Cost Solution:** FPP uses standard **OAuth 2.0 User Credentials (Desktop Client)** with a long-lived **Refresh Token**. Files are uploaded directly to the personal user's 15 GB quota without needing a paid Google Workspace domain or credit card.

### 3. Render Cold-Start Latency
* **Behavior:** After 15 minutes of zero traffic, Render suspends the container. The next HTTP request will experience a 50–90 second delay while the Docker container boots.
* **Frontend Handling:** The React client maintains robust Axios request timeouts and loading indicators so users understand that the free backend is waking up.
