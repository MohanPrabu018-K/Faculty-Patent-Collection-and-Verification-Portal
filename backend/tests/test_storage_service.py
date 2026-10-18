"""Unit and regression tests for StorageService (Local & Cloudflare R2 / S3).

Verifies:
1. Local storage saving, reading, path resolution, and deletion.
2. Security against directory/path traversal attacks in storage keys.
3. Cloudflare R2 / S3 persistent storage synchronization and on-demand restoration
   when container local storage is wiped.
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import upload_settings
from app.services.storage import StorageService, get_storage_service


def test_storage_service_singleton():
    s1 = get_storage_service()
    s2 = get_storage_service()
    assert s1 is s2


def test_local_storage_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setattr(upload_settings, "storage_backend", "local")
    monkeypatch.setattr(upload_settings, "local_storage_root", str(tmp_path))

    service = StorageService()
    assert not service.is_s3_enabled

    key = "fac123/test_patent.pdf"
    content = b"%PDF-1.4 test document content"

    # Save
    saved_path = service.save_file(key, content, "application/pdf")
    assert saved_path.exists()
    assert saved_path.read_bytes() == content

    # Exists
    assert service.file_exists(key)
    assert not service.file_exists("fac123/non_existent.pdf")

    # Get path
    retrieved_path = service.get_file_path(key)
    assert retrieved_path == saved_path

    # Delete
    service.delete_file(key)
    assert not service.file_exists(key)
    assert not saved_path.exists()


def test_path_traversal_prevention(tmp_path, monkeypatch):
    monkeypatch.setattr(upload_settings, "storage_backend", "local")
    monkeypatch.setattr(upload_settings, "local_storage_root", str(tmp_path))

    service = StorageService()

    # Traversal attempts must be blocked
    with pytest.raises(ValueError, match="Path traversal"):
        service.save_file("../evil.pdf", b"evil")

    with pytest.raises(ValueError, match="Path traversal"):
        service.save_file("../../etc/passwd", b"evil")

    assert service.get_file_path("../evil.pdf") is None
    assert service.get_file_path("../../etc/passwd") is None


def test_s3_r2_upload_and_download(tmp_path, monkeypatch):
    monkeypatch.setattr(upload_settings, "storage_backend", "s3")
    monkeypatch.setattr(upload_settings, "local_storage_root", str(tmp_path))
    monkeypatch.setattr(upload_settings, "s3_bucket_name", "faculty-patents")
    monkeypatch.setattr(upload_settings, "s3_access_key_id", "mock-access-key")
    monkeypatch.setattr(upload_settings, "s3_secret_access_key", "mock-secret-key")
    monkeypatch.setattr(upload_settings, "s3_endpoint_url", "https://mock.r2.cloudflarestorage.com")

    service = StorageService()
    assert service.is_s3_enabled

    mock_s3 = MagicMock()
    service._s3_client = mock_s3

    key = "fac999/remote_patent.pdf"
    content = b"%PDF-1.5 persistent content"

    # Save file -> uploads to S3
    saved_path = service.save_file(key, content, "application/pdf")
    assert saved_path.exists()
    mock_s3.put_object.assert_called_once_with(
        Bucket="faculty-patents",
        Key=key,
        Body=content,
        ContentType="application/pdf",
    )

    # Simulate container wipe: remove local file
    saved_path.unlink()
    assert not saved_path.exists()

    # When get_file_path is called, missing local file triggers S3 download_file
    def fake_download_file(Bucket, Key, Filename):
        Path(Filename).write_bytes(content)

    mock_s3.download_file.side_effect = fake_download_file

    restored_path = service.get_file_path(key)
    assert restored_path is not None
    assert restored_path.exists()
    assert restored_path.read_bytes() == content
    mock_s3.download_file.assert_called_once_with(
        Bucket="faculty-patents",
        Key=key,
        Filename=str(restored_path),
    )

    # Delete
    service.delete_file(key)
    mock_s3.delete_object.assert_called_once_with(
        Bucket="faculty-patents",
        Key=key,
    )


def test_rollback_preserves_gdrive_download(tmp_path, monkeypatch):
    """Verify that when rolled back to STORAGE_BACKEND=local, gdrive/ keys can still be retrieved."""
    monkeypatch.setattr(upload_settings, "storage_backend", "local")
    monkeypatch.setattr(upload_settings, "local_storage_root", str(tmp_path))
    monkeypatch.setattr(upload_settings, "google_drive_folder_id", "test_folder")
    monkeypatch.setattr(upload_settings, "google_drive_client_id", "cid")
    monkeypatch.setattr(upload_settings, "google_drive_client_secret", "csec")
    monkeypatch.setattr(upload_settings, "google_drive_refresh_token", "rtok")

    service = StorageService()
    assert not service.is_gdrive_enabled  # New uploads will go to local disk
    assert service.gdrive.is_configured  # Credentials exist for reading previous files

    mock_drive = MagicMock()
    service.gdrive._drive_service = mock_drive

    gdrive_key = "gdrive/file_abc123/patent.pdf"
    content = b"%PDF-1.4 Recovered In Rollback"

    def fake_download(storage_key, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        from app.services.storage import StorageResult
        return StorageResult(dest, storage_key=storage_key, drive_file_id="file_abc123")

    with patch.object(service.gdrive, "download_file", side_effect=fake_download):
        restored = service.get_file_path(gdrive_key)

    assert restored is not None
    assert restored.exists()
    assert restored.read_bytes() == content

