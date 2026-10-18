# Google Drive Storage Provider Setup Guide (₹0 Budget / Free Tier)

This document provides complete instructions for configuring Google Drive as the persistent document storage backend for the **Faculty Patent Collection & Verification Portal (FPP)**.

---

## 1. Architectural Overview & Zero-Cost Guarantee

| Dimension | Specification |
|---|---|
| **Storage Capacity** | **15 GB free** per standard personal Google account (`@gmail.com`) |
| **Financial Cost** | **₹0.00** (Zero billing, no credit card required) |
| **Google Cloud Tier** | Standard Free Tier (OAuth 2.0 Client ID) |
| **Authentication Flow** | OAuth 2.0 User Credentials with Offline Refresh Token |
| **Access Control** | Backend proxy only — documents are **never** shared publicly |
| **Container Resilience** | Automatic on-demand retrieval after Render free-tier container wipe |

### Why OAuth User Credentials Instead of Service Accounts?
On standard personal Google accounts (`@gmail.com`), Google Cloud Service Accounts have an effective **0 byte storage quota** by default. Attempting to upload files into a folder shared with a service account fails with `403: Storage quota has been exceeded for this user`. Service accounts only work with paid Google Workspace Shared Drives or Domain-Wide Delegation.

To achieve **100% free (₹0) operation without a paid Google Workspace subscription**, FPP utilizes standard **OAuth 2.0 User Credentials (Desktop Client)** with a long-lived **Refresh Token**. Uploads run directly on behalf of your personal Google account, utilizing your free 15 GB Google Drive storage pool with zero billing or credit cards needed.

*(Note: For institutions using Google Workspace, Service Account authentication is also supported via `GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON`).*

---

## 2. Step-by-Step Google Cloud Setup (One-Time, 5 Minutes)

### Step 1: Create a Google Cloud Project
1. Open the [Google Cloud Console](https://console.cloud.google.com/).
2. Click the project dropdown at the top and click **New Project**.
3. Name your project (e.g. `Faculty-Patent-Portal`) and click **Create**.
   > *Note: Google Cloud Console does NOT ask for billing or credit cards for this.*

### Step 2: Enable the Google Drive API
1. Navigate to **APIs & Services** > **Library** via the left navigation menu.
2. Search for **Google Drive API**.
3. Click on **Google Drive API** and click the blue **Enable** button.

### Step 3: Configure the OAuth Consent Screen
1. Navigate to **APIs & Services** > **OAuth consent screen**.
2. Select **External** user type and click **Create**.
3. Fill in the required fields:
   - **App name**: `Faculty Patent Portal`
   - **User support email**: Your `@gmail.com` address
   - **Developer contact information**: Your `@gmail.com` address
4. Click **Save and Continue**.
5. On the **Scopes** page, click **Add or Remove Scopes**:
   - Manually add: `https://www.googleapis.com/auth/drive.file`
   - Click **Update** then **Save and Continue**.
6. On the **Test users** page:
   - Click **+ ADD USERS**.
   - Enter your own `@gmail.com` address.
   - Click **Save and Continue**.

### Step 4: Create OAuth 2.0 Client Credentials
1. Navigate to **APIs & Services** > **Credentials**.
2. Click **+ CREATE CREDENTIALS** > **OAuth client ID**.
3. Under **Application type**, select **Desktop app**.
4. Name it (e.g. `FPP Storage Client`) and click **Create**.
5. A modal will display your **Client ID** and **Client Secret**. Keep these open.

---

## 3. Generate Refresh Token Interactively

Run the interactive setup helper in your local terminal:

```bash
python scripts/setup_google_drive.py
```

The script will:
1. Prompt for your **Client ID** and **Client Secret**.
2. Launch a browser window requesting authorization for the `drive.file` scope.
3. Automatically capture your long-lived **Refresh Token**.
4. Create a designated private folder named `Faculty_Patent_Documents` in your Google Drive (or use an existing folder ID).
5. Output the exact configuration block ready for `.env` or Render.

---

## 4. Configuration Reference

### Local Development (`.env`)
```ini
# Persistent Storage Backend
STORAGE_BACKEND=gdrive
LOCAL_STORAGE_ROOT=./storage

# Google Drive Configuration (Personal Account - ₹0)
GOOGLE_DRIVE_FOLDER_ID=1a2b3c4d5e6f7g8h9i0j_your_folder_id
GOOGLE_DRIVE_CLIENT_ID=your_client_id.apps.googleusercontent.com
GOOGLE_DRIVE_CLIENT_SECRET=GOCSPX-your_client_secret
GOOGLE_DRIVE_REFRESH_TOKEN=1//04your_refresh_token
```

### Production Deployment (Render Dashboard)
Add these environment variables under your Render backend web service **Environment** tab:

| Variable | Value | Description |
|---|---|---|
| `STORAGE_BACKEND` | `gdrive` | Switches backend to Google Drive |
| `GOOGLE_DRIVE_FOLDER_ID` | `<folder_id>` | Private folder ID in your Google Drive |
| `GOOGLE_DRIVE_CLIENT_ID` | `<client_id>` | Google Cloud OAuth Client ID |
| `GOOGLE_DRIVE_CLIENT_SECRET` | `<secret>` | Google Cloud OAuth Client Secret |
| `GOOGLE_DRIVE_REFRESH_TOKEN` | `<refresh_token>` | OAuth Refresh Token |

> **Production Safety Feature:**
> In production (`APP_ENV=production`), FPP enforces fail-fast validation. If `STORAGE_BACKEND=gdrive` is set but credentials or folder ID are missing, the backend will immediately raise an explicit error during startup instead of silently falling back to ephemeral local container disk.

---

## 5. Migrating Existing Documents

If you have existing patent files in local storage that need to be migrated to Google Drive:

### 1. Dry Run (Simulate without changes)
```bash
python scripts/migrate_storage_to_gdrive.py --dry-run
```

### 2. Live Migration (Upload + Verify SHA-256)
```bash
python scripts/migrate_storage_to_gdrive.py
```
This utility:
- Reads all `IpFile` records pointing to local disk.
- Calculates local SHA-256 checksum.
- Uploads the document to your private Google Drive folder.
- Downloads the document back from Google Drive and verifies the SHA-256 checksum matches bit-for-bit.
- Updates `IpFile.storage_key` to `gdrive/<file_id>/<filename>` and sets `IpRecord.evidence["drive_file_id"]`.
- Retains local files on disk.

### 3. Optional Local Cleanup
To delete local file copies once verification passes:
```bash
python scripts/migrate_storage_to_gdrive.py --cleanup
```

---

## 6. Verification and Recovery Testing

Run the automated test suite to verify Google Drive functionality:

```bash
# Run Google Drive unit, API, and recovery tests
pytest backend/tests/test_gdrive_storage.py -v

# Run storage service tests
pytest backend/tests/test_storage_service.py -v
```

All operations (upload, authorized download, unauthorized rejection, container wipe recovery, and OCR pipeline re-driving) are fully tested and validated.
