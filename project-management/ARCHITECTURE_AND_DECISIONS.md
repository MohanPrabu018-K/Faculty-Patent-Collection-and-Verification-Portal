# System Architecture & Technical Decisions

**System:** Faculty Patent Collection & Verification Portal (FPP)  
**Author:** Autonomous Engineering Team (Agents 1–13)

---

## 1. High-Level Architecture Diagram

```
┌────────────────────────────────────────────────────────┐
│             Frontend: Cloudflare Pages                 │
│         React 19 + TypeScript + Vite + Axios           │
│        https://faculty-patent-collection-...pages.dev  │
└───────────────────────────┬────────────────────────────┘
                            │ HTTPS (TLS)
                            │ HTTP-only Cookies + CSRF Token
                            ▼
┌────────────────────────────────────────────────────────┐
│            Backend API: Render Free Web Service        │
│          FastAPI + Uvicorn + SQLAlchemy AsyncPG        │
│          https://faculty-patent-portal-api.onrender.com│
│                                                        │
│   ┌────────────────────────────────────────────────┐   │
│   │   11-Agent Deterministic Pipeline (In-Process) │   │
│   │   PyMuPDF -> PaddleOCR -> Tesseract -> Rules   │   │
│   └────────────────────────────────────────────────┘   │
└──────────────┬──────────────────────────┬──────────────┘
               │                          │
    PostgreSQL │                          │ Google Drive API v3
   (Pooled TLS)│                          │ (OAuth2 Refresh Token)
               ▼                          ▼
┌─────────────────────────────┐  ┌───────────────────────────────┐
│ Database: Neon PostgreSQL 16│  │ Storage: Google Drive (15 GB) │
│ - Users, Roles & Departments│  │ - Designated Private Folder   │
│ - IpRecords & IpFiles       │  │ - Encrypted / Private Files   │
│ - Association Requests      │  │ - Zero Cost (Personal @gmail) │
│ - Audit Logs & History      │  │ - Proxy Download via Backend  │
└─────────────────────────────┘  └───────────────────────────────┘
```

---

## 2. Key Architectural Decisions

### ADR-001: Zero-Cost Google Drive Storage Backend
* **Decision:** Replace proposed Cloudflare R2 / S3 paid storage dependency with Google Drive API v3.
* **Authentication Method:** OAuth 2.0 User Credentials (Desktop Client) with long-lived Refresh Token.
* **Rationale:** On personal Google accounts, service accounts have a 0-byte storage quota. OAuth user credentials grant access to the user's free 15 GB quota without enabling billing or providing payment information.
* **Security Guard:** Files are uploaded to a designated private folder. Documents are accessed exclusively through authenticated backend streaming (`GET /api/v1/ip-records/{id}/file`). No public Drive links are ever generated.

### ADR-002: Container Restart & Disk Wipe Recovery
* **Decision:** Transparent on-demand remote file restoration in `storage.py`.
* **Rationale:** Render's free tier spins down after 15 minutes of inactivity and wipes `/data/storage`. When the uvicorn process restarts, any request to download a file or re-drive OCR checks local disk; if missing, it downloads the file from Google Drive to local cache seamlessly.

### ADR-003: Deterministic In-Process Pipeline (No Celery/Redis)
* **Decision:** Schedule the 11-agent document processing pipeline via FastAPI `BackgroundTasks`.
* **Rationale:** Avoids the infrastructure cost and complexity of separate Celery workers and Redis message brokers, preserving the strict ₹0 hosting budget.

### ADR-004: Browser Auth Security & Dual Authentication
* **Decision:** Support both `Authorization: Bearer <jwt>` and HTTP-only `access_token` cookies with `SameSite` and `Secure` attributes, combined with `X-CSRF-Token` validation on state-changing requests.
* **Rationale:** Ensures maximum security against XSS token harvesting in browsers while allowing seamless automated API testing and mobile client interoperability.
