# Risks, Blockers & Mitigation Log

---

## 1. Active Client Action Items & Blockers

| Blocker ID | Description | Severity | Impacted Feature | Mitigation / Action Required | Owner |
|---|---|---|---|---|---|
| **BLK-001** | **One-Time Google Drive OAuth Credentials Generation** | Moderate | Production Document Storage Persistence | Client must create an OAuth 2.0 Desktop Client in Google Cloud Console (₹0, no card needed) and run `scripts/setup_google_drive.py` to generate the `GOOGLE_DRIVE_REFRESH_TOKEN`. | **Client** |
| **BLK-002** | **Render Dashboard Environment Variable Configuration** | Low | Production Storage Activation | Add `STORAGE_BACKEND=gdrive`, `GOOGLE_DRIVE_FOLDER_ID`, `GOOGLE_DRIVE_CLIENT_ID`, `GOOGLE_DRIVE_CLIENT_SECRET`, and `GOOGLE_DRIVE_REFRESH_TOKEN` to Render web service. | **Client** |

---

## 2. Identified Risks & Architectural Mitigations

| Risk ID | Risk Description | Probability | Impact | Architectural Mitigation Implemented |
|---|---|---|---|---|
| **RSK-001** | **Ephemeral Disk Wipe on Render Free Tier** | High (100% on idle spin-down) | Critical | **Mitigated:** All documents are persisted in private Google Drive. Any file missing locally is automatically restored on-demand upon the first read or OCR recovery run. |
| **RSK-002** | **Free-Tier Cold Start Delay (50–90 seconds)** | High | Low/Medium | **Mitigated:** Frontend Axios client includes loading spinners and long timeout tolerances. Users are notified that the backend is waking up. |
| **RSK-003** | **Service Account 0-Byte Storage Quota Trap** | High (if service account used on @gmail) | Critical | **Mitigated:** FPP uses OAuth 2.0 User Credentials (Desktop Client) with Refresh Token, bypassing the 0-byte service account quota and using the user's free 15 GB quota. |
| **RSK-004** | **Google Cloud Billing Accidental Charges** | Low | Critical | **Mitigated:** Standard OAuth Desktop App configuration does not require enabling Cloud Billing or submitting payment details. Verified 100% free. |
| **RSK-005** | **Neon PostgreSQL Free-Tier Inactivity Suspension** | Medium | Low | **Mitigated:** Connection pool automatically wakes up Neon upon request. Reconnection retry logic is implemented in database connection factories. |
