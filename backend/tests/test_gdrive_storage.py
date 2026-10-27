"""Automated tests for Google Drive Storage Provider.

Verifies:
1. GoogleDriveStorage initialization (OAuth2 refresh token and Service Account credentials).
2. Upload flow with mocked Google Drive API v3.
3. Retrieval and container wipe simulation (on-demand download from Drive when local disk is wiped).
4. Existence checks (local cache vs. Drive API files().get).
5. Deletion (local cache and remote files().delete).
6. Production fail-fast safety (silent ephemeral fallback is strictly forbidden in production).
7. End-to-end StorageService integration with Google Drive backend.
8. API Document Upload: persists gdrive file ID and gdrive key in PostgreSQL.
9. API Document Download: authorized download succeeds and restores wiped file; unauthorized download returns 403.
10. OCR / Pipeline Recovery: restores missing file from Google Drive after container wipe and requeues job.
"""
from __future__ import annotations

import io
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from googleapiclient.errors import HttpError
from sqlalchemy import delete, select

from app.core.config import app_settings, upload_settings
from app.core.database import get_async_session_context
from app.core.security import generate_jwt_token, hash_password
from app.main import app
from app.core.exceptions import StorageAuthenticationError, StorageUploadError
from app.models.base import AuditLog, IpFile, IpRecord, ProcessingJob, User
from app.services.storage import GoogleDriveStorage, StorageResult, StorageService, reset_storage_service


@pytest.fixture
def mock_drive_service():
    """Create a mock Google Drive API v3 resource service."""
    service = MagicMock()
    files_resource = MagicMock()
    service.files.return_value = files_resource
    return service


def test_gdrive_is_configured_logic(monkeypatch):
    monkeypatch.setattr(upload_settings, "storage_backend", "gdrive")
    monkeypatch.setattr(upload_settings, "google_drive_folder_id", "test_folder_id")
    monkeypatch.setattr(upload_settings, "google_drive_client_id", "test_client_id")
    monkeypatch.setattr(upload_settings, "google_drive_client_secret", "test_secret")
    monkeypatch.setattr(upload_settings, "google_drive_refresh_token", "test_refresh_token")

    gdrive = GoogleDriveStorage()
    assert gdrive.is_configured
    assert gdrive.auth_mode == "oauth_user"

    # Missing folder_id
    monkeypatch.setattr(upload_settings, "google_drive_folder_id", None)
    gdrive_missing = GoogleDriveStorage()
    assert not gdrive_missing.is_configured


def test_gdrive_upload_success(tmp_path, monkeypatch, mock_drive_service):
    monkeypatch.setattr(upload_settings, "storage_backend", "gdrive")
    monkeypatch.setattr(upload_settings, "local_storage_root", str(tmp_path))
    monkeypatch.setattr(upload_settings, "google_drive_folder_id", "test_folder_123")
    monkeypatch.setattr(upload_settings, "google_drive_client_id", "cid")
    monkeypatch.setattr(upload_settings, "google_drive_client_secret", "csecret")
    monkeypatch.setattr(upload_settings, "google_drive_refresh_token", "rtoken")

    storage = GoogleDriveStorage(local_root=tmp_path)
    storage._drive_service = mock_drive_service

    # Configure mock files().create(...)
    create_request = MagicMock()
    create_request.execute.return_value = {
        "id": "drive_file_abc123",
        "name": "fac_01_patent_sample.pdf",
    }
    mock_drive_service.files().create.return_value = create_request

    content = b"%PDF-1.4 Mock Patent Document For Google Drive"

    drive_file_id, effective_key = storage.upload_file(
        data=content,
        original_name="patent_sample.pdf",
        storage_key="fac_01/patent_sample.pdf",
        content_type="application/pdf",
    )

    assert drive_file_id == "drive_file_abc123"
    assert effective_key == "gdrive/drive_file_abc123/patent_sample.pdf"

    # Verify API invocation arguments
    mock_drive_service.files().create.assert_called_once()
    call_kwargs = mock_drive_service.files().create.call_args[1]
    assert call_kwargs["body"]["name"] == "fac_01_patent_sample.pdf"
    assert call_kwargs["body"]["parents"] == ["test_folder_123"]
    assert call_kwargs["fields"] == "id, name, size"


def test_gdrive_download_restores_file_after_wipe(tmp_path, monkeypatch, mock_drive_service):
    """Simulate Render free-tier container restart: local disk is empty, file restored from Drive."""
    monkeypatch.setattr(upload_settings, "storage_backend", "gdrive")
    monkeypatch.setattr(upload_settings, "local_storage_root", str(tmp_path))
    monkeypatch.setattr(upload_settings, "google_drive_folder_id", "test_folder_123")
    monkeypatch.setattr(upload_settings, "google_drive_client_id", "cid")
    monkeypatch.setattr(upload_settings, "google_drive_client_secret", "csecret")
    monkeypatch.setattr(upload_settings, "google_drive_refresh_token", "rtoken")

    storage = GoogleDriveStorage(local_root=tmp_path)
    storage._drive_service = mock_drive_service

    file_bytes = b"%PDF-1.7 Recovered Document Content From Google Drive"

    # Mock MediaIoBaseDownload
    def mock_download_side_effect(fh, request):
        fh.write(file_bytes)
        downloader = MagicMock()
        downloader.next_chunk.return_value = (None, True)
        return downloader

    destination_path = tmp_path / "gdrive" / "drive_id_xyz789" / "restored.pdf"
    assert not destination_path.exists()

    with patch("googleapiclient.http.MediaIoBaseDownload", side_effect=mock_download_side_effect):
        res = storage.download_file("gdrive/drive_id_xyz789/restored.pdf", destination_path)

    assert res is not None
    assert destination_path.exists()
    assert destination_path.read_bytes() == file_bytes
    assert res.drive_file_id == "drive_id_xyz789"
    assert res.storage_key == "gdrive/drive_id_xyz789/restored.pdf"


def test_gdrive_file_exists(tmp_path, monkeypatch, mock_drive_service):
    monkeypatch.setattr(upload_settings, "storage_backend", "gdrive")
    monkeypatch.setattr(upload_settings, "local_storage_root", str(tmp_path))
    monkeypatch.setattr(upload_settings, "google_drive_folder_id", "test_folder_123")
    monkeypatch.setattr(upload_settings, "google_drive_client_id", "cid")
    monkeypatch.setattr(upload_settings, "google_drive_client_secret", "csecret")
    monkeypatch.setattr(upload_settings, "google_drive_refresh_token", "rtoken")

    storage = GoogleDriveStorage(local_root=tmp_path)
    storage._drive_service = mock_drive_service

    # 1. Existing file
    get_request = MagicMock()
    get_request.execute.return_value = {"id": "drive_id_111", "trashed": False}
    mock_drive_service.files().get.return_value = get_request

    assert storage.file_exists("gdrive/drive_id_111/doc.pdf")

    # 2. Trashed file
    get_request.execute.return_value = {"id": "drive_id_111", "trashed": True}
    assert not storage.file_exists("gdrive/drive_id_111/doc.pdf")

    # 3. 404 Not Found HttpError
    mock_resp = MagicMock(status=404, reason="Not Found")
    mock_drive_service.files().get.side_effect = HttpError(resp=mock_resp, content=b"Not Found")
    assert not storage.file_exists("gdrive/drive_id_not_found/doc.pdf")


def test_gdrive_delete_file(tmp_path, monkeypatch, mock_drive_service):
    monkeypatch.setattr(upload_settings, "storage_backend", "gdrive")
    monkeypatch.setattr(upload_settings, "local_storage_root", str(tmp_path))
    monkeypatch.setattr(upload_settings, "google_drive_folder_id", "test_folder_123")
    monkeypatch.setattr(upload_settings, "google_drive_client_id", "cid")
    monkeypatch.setattr(upload_settings, "google_drive_client_secret", "csecret")
    monkeypatch.setattr(upload_settings, "google_drive_refresh_token", "rtoken")

    storage = GoogleDriveStorage(local_root=tmp_path)
    storage._drive_service = mock_drive_service

    delete_request = MagicMock()
    delete_request.execute.return_value = None
    mock_drive_service.files().delete.return_value = delete_request

    storage.delete_file("gdrive/drive_id_del/test.pdf")
    mock_drive_service.files().delete.assert_called_once_with(fileId="drive_id_del", supportsAllDrives=True)


def test_production_fail_fast_when_unconfigured(tmp_path, monkeypatch):
    """Ensure that in production, missing credentials raises rather than silently falling back."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setattr(upload_settings, "storage_backend", "gdrive")
    monkeypatch.setattr(upload_settings, "local_storage_root", str(tmp_path))
    monkeypatch.setattr(upload_settings, "google_drive_folder_id", None)
    monkeypatch.setattr(upload_settings, "google_drive_client_id", None)
    monkeypatch.setattr(upload_settings, "google_drive_refresh_token", None)

    service = StorageService()
    assert service.is_gdrive_enabled
    assert not service.gdrive.is_configured

    # save_file must fail in production
    with pytest.raises(RuntimeError, match="Production STORAGE_BACKEND=gdrive"):
        service.save_file("test/doc.pdf", b"data")

    # get_file_path must fail in production if local cache is missing
    with pytest.raises(RuntimeError, match="Production STORAGE_BACKEND=gdrive"):
        service.get_file_path("gdrive/some_id/doc.pdf")


def test_storage_service_e2e_with_gdrive(tmp_path, monkeypatch, mock_drive_service):
    """Verify StorageService transparently handles save, exists, wipe, restore, and delete."""
    monkeypatch.setattr(upload_settings, "storage_backend", "gdrive")
    monkeypatch.setattr(upload_settings, "local_storage_root", str(tmp_path))
    monkeypatch.setattr(upload_settings, "google_drive_folder_id", "target_folder")
    monkeypatch.setattr(upload_settings, "google_drive_client_id", "cid")
    monkeypatch.setattr(upload_settings, "google_drive_client_secret", "csec")
    monkeypatch.setattr(upload_settings, "google_drive_refresh_token", "rtok")

    service = StorageService()
    service.gdrive._drive_service = mock_drive_service

    # Setup mock upload
    create_req = MagicMock()
    create_req.execute.return_value = {"id": "id_12345", "name": "fac_100_test.pdf"}
    mock_drive_service.files().create.return_value = create_req

    data = b"%PDF-1.4 Storage Service Google Drive Test"
    key = "fac_100/test.pdf"

    # 1. Save file
    saved = service.save_file(key, data, "application/pdf")
    assert saved.exists()
    assert saved.read_bytes() == data
    assert saved.drive_file_id == "id_12345"
    assert saved.storage_key == "gdrive/id_12345/test.pdf"

    # 2. Check exists (finds it in local cache without API call)
    assert service.file_exists(saved.storage_key)

    # 3. Simulate container disk wipe: remove local cached file
    saved.unlink()
    assert not saved.exists()

    # Setup mock download
    def mock_dl(fh, req):
        fh.write(data)
        d = MagicMock()
        d.next_chunk.return_value = (None, True)
        return d

    with patch("googleapiclient.http.MediaIoBaseDownload", side_effect=mock_dl):
        restored = service.get_file_path(saved.storage_key)

    assert restored is not None
    assert restored.exists()
    assert restored.read_bytes() == data
    assert restored.storage_key == "gdrive/id_12345/test.pdf"

    # 4. Delete file
    del_req = MagicMock()
    del_req.execute.return_value = None
    mock_drive_service.files().delete.return_value = del_req

    service.delete_file(saved.storage_key)
    assert not restored.exists()
    mock_drive_service.files().delete.assert_called_once_with(fileId="id_12345", supportsAllDrives=True)


@pytest.mark.asyncio
async def test_api_upload_persists_gdrive_metadata(tmp_path, monkeypatch, mock_drive_service):
    """End-to-end API upload with Google Drive: verifies PostgreSQL persistence of Drive file ID and key."""
    reset_storage_service()
    monkeypatch.setattr(upload_settings, "storage_backend", "gdrive")
    monkeypatch.setattr(upload_settings, "local_storage_root", str(tmp_path))
    monkeypatch.setattr(upload_settings, "google_drive_folder_id", "folder_test")
    monkeypatch.setattr(upload_settings, "google_drive_client_id", "cid")
    monkeypatch.setattr(upload_settings, "google_drive_client_secret", "csec")
    monkeypatch.setattr(upload_settings, "google_drive_refresh_token", "rtok")

    user_id = f"usr-{uuid.uuid4().hex[:8]}"
    email = f"{user_id}@university.edu"

    async with get_async_session_context() as db:
        user = User(
            id=user_id,
            email=email,
            official_email=email,
            password_hash=hash_password("Pass123!"),
            full_name="Dr. Drive Uploader",
            role="faculty",
            faculty_id=f"FAC-{user_id[:6]}",
            status="active",
            is_active=True,
        )
        db.add(user)
        await db.commit()

    token = generate_jwt_token(
        subject=user_id,
        secret=app_settings.secret_key,
        algorithm=app_settings.jwt_algorithm,
        minutes=30,
        email=email,
        role="faculty",
        faculty_id=user.faculty_id,
    )

    create_req = MagicMock()
    create_req.execute.return_value = {"id": "gdrive_id_api_upload_99", "name": "patent.pdf"}
    mock_drive_service.files().create.return_value = create_req

    # Attach mock to storage singleton
    with patch("app.services.storage.GoogleDriveStorage._get_drive_service", return_value=mock_drive_service):
        pdf_bytes = b"%PDF-1.4 Mock Upload Patent Content"
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/uploads/",
                headers={"Authorization": f"Bearer {token}"},
                files={"file": ("patent.pdf", pdf_bytes, "application/pdf")},
            )

        assert resp.status_code == 202, resp.text
        data = resp.json()
        record_id = data["ip_record_id"]

    # Verify database state
    async with get_async_session_context() as db:
        rec = (await db.execute(select(IpRecord).where(IpRecord.id == record_id))).scalar_one()
        file_row = (await db.execute(select(IpFile).where(IpFile.ip_record_id == record_id))).scalar_one()

        assert rec.evidence.get("drive_file_id") == "gdrive_id_api_upload_99"
        assert rec.evidence.get("storage_backend") == "gdrive"
        assert file_row.storage_key == "gdrive/gdrive_id_api_upload_99/patent.pdf"

        # Cleanup test entities
        await db.execute(delete(AuditLog).where(AuditLog.actor_id == user_id))
        await db.execute(delete(ProcessingJob).where(ProcessingJob.ip_record_id == record_id))
        await db.execute(delete(IpFile).where(IpFile.ip_record_id == record_id))
        await db.execute(delete(IpRecord).where(IpRecord.id == record_id))
        await db.execute(delete(User).where(User.id == user_id))
        await db.commit()

    reset_storage_service()


@pytest.mark.asyncio
async def test_api_authorized_download_restores_from_drive_and_blocks_unauthorized(
    tmp_path, monkeypatch, mock_drive_service
):
    """Test authorized download recovers from Drive after container wipe; unauthorized user is denied."""
    reset_storage_service()
    monkeypatch.setattr(upload_settings, "storage_backend", "gdrive")
    monkeypatch.setattr(upload_settings, "local_storage_root", str(tmp_path))
    monkeypatch.setattr(upload_settings, "google_drive_folder_id", "folder_test")
    monkeypatch.setattr(upload_settings, "google_drive_client_id", "cid")
    monkeypatch.setattr(upload_settings, "google_drive_client_secret", "csec")
    monkeypatch.setattr(upload_settings, "google_drive_refresh_token", "rtok")

    owner_id = f"owner-{uuid.uuid4().hex[:8]}"
    intruder_id = f"intruder-{uuid.uuid4().hex[:8]}"
    record_id = str(uuid.uuid4())
    drive_file_id = "gdrive_file_dl_42"
    doc_content = b"%PDF-1.4 Secret Faculty Patent PDF"
    storage_key = f"gdrive/{drive_file_id}/confidential.pdf"

    try:
        async with get_async_session_context() as db:
            owner = User(
                id=owner_id,
                email=f"{owner_id}@univ.edu",
                official_email=f"{owner_id}@univ.edu",
                password_hash=hash_password("Pass123!"),
                full_name="Dr. Owner",
                role="faculty",
                faculty_id=f"FAC-O-{uuid.uuid4().hex[:6]}",
                status="active",
                is_active=True,
            )
            intruder = User(
                id=intruder_id,
                email=f"{intruder_id}@univ.edu",
                official_email=f"{intruder_id}@univ.edu",
                password_hash=hash_password("Pass123!"),
                full_name="Dr. Intruder",
                role="faculty",
                faculty_id=f"FAC-I-{uuid.uuid4().hex[:6]}",
                status="active",
                is_active=True,
            )
            db.add_all([owner, intruder])
            await db.flush()

            record = IpRecord(
                id=record_id,
                uploader_id=owner_id,
                ip_type="PATENT",
                processing_status="COMPLETED",
                verification_status="UNVERIFIED",
                evidence={"drive_file_id": drive_file_id, "storage_backend": "gdrive"},
            )
            db.add(record)
            await db.flush()

            ip_file = IpFile(
                id=str(uuid.uuid4()),
                ip_record_id=record_id,
                storage_key=storage_key,
                original_filename="confidential.pdf",
                file_extension=".pdf",
                file_size_bytes=len(doc_content),
                mime_type="application/pdf",
                uploaded_by=owner_id,
                upload_status="COMPLETED",
            )
            db.add(ip_file)
            await db.commit()

        owner_token = generate_jwt_token(
            subject=owner_id,
            secret=app_settings.secret_key,
            algorithm=app_settings.jwt_algorithm,
            minutes=30,
            email=owner.email,
            role="faculty",
        )
        intruder_token = generate_jwt_token(
            subject=intruder_id,
            secret=app_settings.secret_key,
            algorithm=app_settings.jwt_algorithm,
            minutes=30,
            email=intruder.email,
            role="faculty",
        )

        # 1. Ensure local container cache does NOT have the file (simulate Render container wipe)
        cached_path = tmp_path / "gdrive" / drive_file_id / "confidential.pdf"
        assert not cached_path.exists()

        # Mock download side effect
        def mock_dl(fh, req):
            fh.write(doc_content)
            d = MagicMock()
            d.next_chunk.return_value = (None, True)
            return d

        with patch("app.services.storage.GoogleDriveStorage._get_drive_service", return_value=mock_drive_service), \
             patch("googleapiclient.http.MediaIoBaseDownload", side_effect=mock_dl):
            with TestClient(app) as client:
                # 2. Unauthorized access attempt -> 403 Forbidden
                unauth_resp = client.get(
                    f"/api/v1/ip-records/{record_id}/file",
                    headers={"Authorization": f"Bearer {intruder_token}"},
                )
                assert unauth_resp.status_code == 403

                # 3. Authorized owner access -> 200 OK + streamed content
                auth_resp = client.get(
                    f"/api/v1/ip-records/{record_id}/file",
                    headers={"Authorization": f"Bearer {owner_token}"},
                )
                assert auth_resp.status_code == 200
                assert auth_resp.content == doc_content
                assert "confidential.pdf" in auth_resp.headers.get("content-disposition", "")

        # 4. Verify the document was restored and cached locally
        assert cached_path.exists()
        assert cached_path.read_bytes() == doc_content
    finally:
        # Cleanup
        async with get_async_session_context() as db:
            await db.execute(delete(AuditLog).where(AuditLog.actor_id.in_([owner_id, intruder_id])))
            await db.execute(delete(IpFile).where(IpFile.ip_record_id == record_id))
            await db.execute(delete(IpRecord).where(IpRecord.id == record_id))
            await db.execute(delete(User).where(User.id.in_([owner_id, intruder_id])))
            await db.commit()

        reset_storage_service()


def test_pipeline_recovery_restores_from_gdrive(tmp_path, monkeypatch, mock_drive_service):
    """Verify requeue_stuck_pipelines restores a wiped document from Google Drive and resumes processing."""
    from datetime import datetime, timedelta, timezone
    from app.workers.orchestrator_task import requeue_stuck_pipelines
    from app.core.database import get_session

    reset_storage_service()
    monkeypatch.setattr(upload_settings, "storage_backend", "gdrive")
    monkeypatch.setattr(upload_settings, "local_storage_root", str(tmp_path))
    monkeypatch.setattr(upload_settings, "google_drive_folder_id", "folder_recovery")
    monkeypatch.setattr(upload_settings, "google_drive_client_id", "cid")
    monkeypatch.setattr(upload_settings, "google_drive_client_secret", "csec")
    monkeypatch.setattr(upload_settings, "google_drive_refresh_token", "rtok")

    record_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    user_id = f"usr-rec-{uuid.uuid4().hex[:8]}"
    drive_file_id = "drive_stuck_file_77"
    doc_bytes = b"%PDF-1.4 Stuck Patent Document Recovered From Drive"
    storage_key = f"gdrive/{drive_file_id}/stuck_doc.pdf"

    # Insert stuck job and record in DB
    session = get_session()
    try:
        uploader = User(
            id=user_id,
            email=f"{user_id}@univ.edu",
            official_email=f"{user_id}@univ.edu",
            password_hash=hash_password("Pass123!"),
            full_name="Dr. Recovery Uploader",
            role="faculty",
            faculty_id=f"FAC-R-{uuid.uuid4().hex[:6]}",
            status="active",
            is_active=True,
        )
        session.add(uploader)
        session.flush()

        record = IpRecord(
            id=record_id,
            uploader_id=user_id,
            ip_type="PATENT",
            processing_status="PROCESSING",
            verification_status="UNVERIFIED",
            evidence={"drive_file_id": drive_file_id, "storage_backend": "gdrive"},
        )
        session.add(record)
        session.flush()

        # Job created 2 hours ago
        stuck_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2)
        job = ProcessingJob(
            id=job_id,
            ip_record_id=record_id,
            job_type="orchestrator",
            status="PROCESSING",
            retry_count=0,
            max_retries=3,
            created_at=stuck_time,
        )
        session.add(job)

        ip_file = IpFile(
            id=str(uuid.uuid4()),
            ip_record_id=record_id,
            storage_key=storage_key,
            original_filename="stuck_doc.pdf",
            file_extension=".pdf",
            file_size_bytes=len(doc_bytes),
            upload_status="COMPLETED",
        )
        session.add(ip_file)
        session.commit()
    finally:
        session.close()

    # Verify local file is completely absent (container disk wipe)
    destination_path = tmp_path / "gdrive" / drive_file_id / "stuck_doc.pdf"
    assert not destination_path.exists()

    def mock_dl(fh, req):
        fh.write(doc_bytes)
        d = MagicMock()
        d.next_chunk.return_value = (None, True)
        return d

    mock_run_pipeline = MagicMock()

    try:
        with patch("app.services.storage.GoogleDriveStorage._get_drive_service", return_value=mock_drive_service), \
             patch("googleapiclient.http.MediaIoBaseDownload", side_effect=mock_dl), \
             patch("app.workers.orchestrator_task.run_document_pipeline", mock_run_pipeline):
            recovery_result = requeue_stuck_pipelines(stuck_after_seconds=60)

        # 1. Recovery detected the stuck job and requeued it
        assert record_id in recovery_result["requeued"]

        # 2. File was restored to local cache
        assert destination_path.exists()
        assert destination_path.read_bytes() == doc_bytes

        # 3. Pipeline was invoked with restored local path
        mock_run_pipeline.assert_called_once_with(str(destination_path), record_id)
    finally:
        # Cleanup
        session = get_session()
        try:
            session.execute(delete(ProcessingJob).where(ProcessingJob.ip_record_id == record_id))
            session.execute(delete(IpFile).where(IpFile.ip_record_id == record_id))
            session.execute(delete(IpRecord).where(IpRecord.id == record_id))
            session.execute(delete(User).where(User.id == user_id))
            session.commit()
        finally:
            session.close()

        reset_storage_service()


def test_gdrive_upload_fails_fast_on_invalid_grant_without_retries(tmp_path, monkeypatch, mock_drive_service):
    """Permanent OAuth failure (invalid_grant) must fail fast on attempt 1 without 3 futile retries."""
    monkeypatch.setattr(upload_settings, "storage_backend", "gdrive")
    monkeypatch.setattr(upload_settings, "local_storage_root", str(tmp_path))
    monkeypatch.setattr(upload_settings, "google_drive_folder_id", "folder_test")
    monkeypatch.setattr(upload_settings, "google_drive_client_id", "cid")
    monkeypatch.setattr(upload_settings, "google_drive_client_secret", "csec")
    monkeypatch.setattr(upload_settings, "google_drive_refresh_token", "rtok")

    storage = GoogleDriveStorage(local_root=tmp_path)
    storage._drive_service = mock_drive_service

    create_req = MagicMock()
    create_req.execute.side_effect = Exception("invalid_grant: Token has been expired or revoked.")
    mock_drive_service.files().create.return_value = create_req

    with pytest.raises(StorageAuthenticationError, match="requires reauthorization"):
        storage.upload_file(
            data=b"test data",
            original_name="test.pdf",
            storage_key="user/test.pdf",
            content_type="application/pdf",
        )

    # Must have failed on first attempt without 3 retries
    assert create_req.execute.call_count == 1
    assert storage._reauthorization_required is True

    # Immediate fail-fast on second call before even calling files().create
    with pytest.raises(StorageAuthenticationError, match="requires reauthorization"):
        storage.upload_file(
            data=b"test data 2",
            original_name="test2.pdf",
            storage_key="user/test2.pdf",
            content_type="application/pdf",
        )
    assert create_req.execute.call_count == 1  # Not called again


def test_gdrive_upload_retries_transient_error_and_succeeds(tmp_path, monkeypatch, mock_drive_service):
    """Transient errors (HTTP 429, 503) are retried with backoff and succeed."""
    monkeypatch.setattr(upload_settings, "storage_backend", "gdrive")
    monkeypatch.setattr(upload_settings, "local_storage_root", str(tmp_path))
    monkeypatch.setattr(upload_settings, "google_drive_folder_id", "folder_test")
    monkeypatch.setattr(upload_settings, "google_drive_client_id", "cid")
    monkeypatch.setattr(upload_settings, "google_drive_client_secret", "csec")
    monkeypatch.setattr(upload_settings, "google_drive_refresh_token", "rtok")

    storage = GoogleDriveStorage(local_root=tmp_path)
    storage._drive_service = mock_drive_service

    mock_resp_429 = MagicMock(status=429, reason="Too Many Requests")
    mock_resp_503 = MagicMock(status=503, reason="Service Unavailable")

    create_req = MagicMock()
    create_req.execute.side_effect = [
        HttpError(resp=mock_resp_429, content=b"rateLimitExceeded"),
        HttpError(resp=mock_resp_503, content=b"backendError"),
        {"id": "drive_recovered_999", "name": "user_doc.pdf"},
    ]
    mock_drive_service.files().create.return_value = create_req

    with patch("time.sleep") as mock_sleep:
        file_id, key = storage.upload_file(
            data=b"content",
            original_name="doc.pdf",
            storage_key="user/doc.pdf",
            content_type="application/pdf",
        )

    assert file_id == "drive_recovered_999"
    assert key == "gdrive/drive_recovered_999/doc.pdf"
    assert create_req.execute.call_count == 3
    assert mock_sleep.call_count == 2


def test_gdrive_upload_non_retryable_error_fails_immediately(tmp_path, monkeypatch, mock_drive_service):
    """Non-retryable HTTP 403 Forbidden halts immediately without retries."""
    monkeypatch.setattr(upload_settings, "storage_backend", "gdrive")
    monkeypatch.setattr(upload_settings, "local_storage_root", str(tmp_path))
    monkeypatch.setattr(upload_settings, "google_drive_folder_id", "folder_test")
    monkeypatch.setattr(upload_settings, "google_drive_client_id", "cid")
    monkeypatch.setattr(upload_settings, "google_drive_client_secret", "csec")
    monkeypatch.setattr(upload_settings, "google_drive_refresh_token", "rtok")

    storage = GoogleDriveStorage(local_root=tmp_path)
    storage._drive_service = mock_drive_service

    mock_resp_403 = MagicMock(status=403, reason="Forbidden")
    create_req = MagicMock()
    create_req.execute.side_effect = HttpError(resp=mock_resp_403, content=b"forbidden")
    mock_drive_service.files().create.return_value = create_req

    with pytest.raises(StorageUploadError, match="Failed to upload file to Google Drive"):
        storage.upload_file(
            data=b"content",
            original_name="doc.pdf",
            storage_key="user/doc.pdf",
            content_type="application/pdf",
        )

    assert create_req.execute.call_count == 1


def test_gdrive_check_status_is_sanitized(tmp_path, monkeypatch):
    """check_status() returns diagnostic info and never exposes secrets or tokens."""
    monkeypatch.setattr(upload_settings, "storage_backend", "gdrive")
    monkeypatch.setattr(upload_settings, "local_storage_root", str(tmp_path))
    monkeypatch.setattr(upload_settings, "google_drive_folder_id", "folder_secret_123")
    monkeypatch.setattr(upload_settings, "google_drive_client_id", "secret_client_id")
    monkeypatch.setattr(upload_settings, "google_drive_client_secret", "secret_secret")
    monkeypatch.setattr(upload_settings, "google_drive_refresh_token", "secret_refresh_token")

    storage = GoogleDriveStorage(local_root=tmp_path)
    status_info = storage.check_status()

    assert status_info["backend"] == "gdrive"
    assert status_info["configured"] is True
    assert status_info["has_folder_id"] is True
    assert status_info["reauthorization_required"] is False

    # Ensure no secrets leak
    status_str = str(status_info)
    assert "secret_client_id" not in status_str
    assert "secret_secret" not in status_str
    assert "secret_refresh_token" not in status_str


def test_storage_service_save_file_cleans_up_local_file_on_gdrive_failure(tmp_path, monkeypatch, mock_drive_service):
    """When remote upload fails, any temporary local file is cleaned up so no orphaned files remain."""
    monkeypatch.setattr(upload_settings, "storage_backend", "gdrive")
    monkeypatch.setattr(upload_settings, "local_storage_root", str(tmp_path))
    monkeypatch.setattr(upload_settings, "google_drive_folder_id", "folder_test")
    monkeypatch.setattr(upload_settings, "google_drive_client_id", "cid")
    monkeypatch.setattr(upload_settings, "google_drive_client_secret", "csec")
    monkeypatch.setattr(upload_settings, "google_drive_refresh_token", "rtok")

    service = StorageService()
    service.gdrive._drive_service = mock_drive_service

    create_req = MagicMock()
    create_req.execute.side_effect = Exception("invalid_grant: Token has been expired or revoked.")
    mock_drive_service.files().create.return_value = create_req

    key = "user_orphantest/failed_doc.pdf"
    expected_local = tmp_path / key

    with pytest.raises(StorageAuthenticationError):
        service.save_file(
            storage_key=key,
            data=b"temporary bytes",
            content_type="application/pdf",
        )

    # Local file must NOT remain on disk
    assert not expected_local.exists()


@pytest.mark.asyncio
async def test_api_upload_storage_auth_error_returns_503_and_no_db_records(tmp_path, monkeypatch, mock_drive_service):
    """When storage raises StorageAuthenticationError, API returns 503 and leaves NO orphaned DB records."""
    reset_storage_service()
    monkeypatch.setattr(upload_settings, "storage_backend", "gdrive")
    monkeypatch.setattr(upload_settings, "local_storage_root", str(tmp_path))
    monkeypatch.setattr(upload_settings, "google_drive_folder_id", "folder_test")
    monkeypatch.setattr(upload_settings, "google_drive_client_id", "cid")
    monkeypatch.setattr(upload_settings, "google_drive_client_secret", "csec")
    monkeypatch.setattr(upload_settings, "google_drive_refresh_token", "rtok")

    user_id = f"usr-{uuid.uuid4().hex[:8]}"
    email = f"{user_id}@university.edu"

    async with get_async_session_context() as db:
        user = User(
            id=user_id,
            email=email,
            official_email=email,
            password_hash=hash_password("Pass123!"),
            full_name="Dr. Failed Uploader",
            role="faculty",
            faculty_id=f"FAC-{user_id[:6]}",
            status="active",
            is_active=True,
        )
        db.add(user)
        await db.commit()

    token = generate_jwt_token(
        subject=user_id,
        secret=app_settings.secret_key,
        algorithm=app_settings.jwt_algorithm,
        minutes=30,
        email=email,
        role="faculty",
        faculty_id=user.faculty_id,
    )

    create_req = MagicMock()
    create_req.execute.side_effect = Exception("invalid_grant: Token has been expired or revoked.")
    mock_drive_service.files().create.return_value = create_req

    try:
        with patch("app.services.storage.GoogleDriveStorage._get_drive_service", return_value=mock_drive_service):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/uploads/",
                    headers={"Authorization": f"Bearer {token}"},
                    files={"file": ("certificate.pdf", b"%PDF-1.4 Data", "application/pdf")},
                )

        assert resp.status_code == 503
        data = resp.json()
        assert data["error"] == "STORAGE_AUTH_ERROR"
        assert "requires reauthorization" in data["message"]
        # Ensure no raw tokens or client secret leak in message
        assert "rtok" not in data["message"]
        assert "csec" not in data["message"]

        # Confirm NO records were inserted into the database
        async with get_async_session_context() as db:
            records = (await db.execute(select(IpRecord).where(IpRecord.uploader_id == user_id))).scalars().all()
            assert len(records) == 0

    finally:
        async with get_async_session_context() as db:
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()
        reset_storage_service()


def test_gdrive_token_refresh_lifecycle(tmp_path, monkeypatch):
    """Test refresh_access_token handling for successful refresh and permanent invalid_grant."""
    from google.auth.exceptions import RefreshError

    monkeypatch.setattr(upload_settings, "storage_backend", "gdrive")
    monkeypatch.setattr(upload_settings, "local_storage_root", str(tmp_path))
    monkeypatch.setattr(upload_settings, "google_drive_folder_id", "folder_test")
    monkeypatch.setattr(upload_settings, "google_drive_client_id", "cid")
    monkeypatch.setattr(upload_settings, "google_drive_client_secret", "csec")
    monkeypatch.setattr(upload_settings, "google_drive_refresh_token", "rtok")

    storage = GoogleDriveStorage(local_root=tmp_path)

    # 1. Successful refresh
    mock_creds = MagicMock()
    mock_creds.token = "refreshed_access_token_123"
    storage._credentials = mock_creds

    token = storage.refresh_access_token()
    assert token == "refreshed_access_token_123"
    assert storage._reauthorization_required is False

    # 2. Permanent RefreshError (invalid_grant)
    mock_creds.refresh.side_effect = RefreshError(
        "('invalid_grant: Token has been expired or revoked.', {'error': 'invalid_grant'})"
    )

    with pytest.raises(StorageAuthenticationError, match="requires reauthorization"):
        storage.refresh_access_token()

    assert storage._reauthorization_required is True
    assert storage._last_auth_error is not None


