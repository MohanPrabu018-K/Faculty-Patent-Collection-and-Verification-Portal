"""Persistent Storage Service for Faculty Patent Portal (FPP).

Supports:
1. Local filesystem storage (default, used for local development and hermetic automated tests).
2. Google Drive API storage (100% Free / ₹0 cost using a standard 15GB Google account and OAuth2
   refresh token, or Google Cloud Service Account).
3. S3-compatible cloud storage (Cloudflare R2, AWS S3).

Zero-Data-Loss Architecture:
- Uploads are saved to the local cache and pushed to Google Drive (or S3).
- On container spin-down or redeploy on Render's free tier (where /data/storage is wiped),
  any subsequent request (OCR pipeline, pipeline recovery, or user file download)
  automatically fetches the file from Google Drive on-demand and caches it locally.
- In production (APP_ENV=production/staging), silent fallback to ephemeral storage is blocked.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import socket
import ssl
import threading
import time
from pathlib import Path
from typing import Any

import structlog

from app.core.config import upload_settings
from app.core.exceptions import StorageAuthenticationError, StorageUploadError

logger = structlog.get_logger(__name__)


class StorageResult(os.PathLike[str]):
    """Wrapper around a local Path that exposes storage_key and drive_file_id.

    Delegates all filesystem attributes and methods (__getattr__, __fspath__, __str__)
    to the underlying Path object so it can be passed directly to open(), FileResponse,
    or any Path-consuming function.
    """

    def __init__(
        self,
        path: Path,
        storage_key: str,
        drive_file_id: str | None = None,
    ) -> None:
        self._path = path
        self.storage_key = storage_key
        self.drive_file_id = drive_file_id
        self.file_id = drive_file_id

    def __getattr__(self, name: str) -> Any:
        return getattr(self._path, name)

    def __fspath__(self) -> str:
        return str(self._path)

    def __str__(self) -> str:
        return str(self._path)

    def __repr__(self) -> str:
        return f"StorageResult(path={self._path!r}, storage_key={self.storage_key!r}, drive_file_id={self.drive_file_id!r})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, StorageResult):
            return self._path == other._path
        if isinstance(other, Path):
            return self._path == other
        if isinstance(other, (os.PathLike, str)):
            return str(self._path) == str(other)
        return False

    def __hash__(self) -> int:
        return hash(self._path)


class GoogleDriveStorage:
    """Google Drive API storage provider using OAuth2 user credentials or Service Account."""

    SCOPES = ["https://www.googleapis.com/auth/drive.file"]

    def __init__(self, local_root: Path | None = None) -> None:
        self.local_root = local_root if local_root is not None else Path(upload_settings.local_storage_root)
        self.folder_id = (upload_settings.google_drive_folder_id or "").strip()
        self.client_id = (upload_settings.google_drive_client_id or "").strip()
        self.client_secret = (upload_settings.google_drive_client_secret or "").strip()
        self.refresh_token = (upload_settings.google_drive_refresh_token or "").strip()
        self.service_account_json = (upload_settings.google_drive_service_account_json or "").strip()
        self._drive_service: Any = None
        self._credentials: Any = None
        self._reauthorization_required: bool = False
        self._last_auth_error: str | None = None
        self._lock = threading.Lock()

    @property
    def auth_mode(self) -> str:
        if self.refresh_token:
            return "oauth_user"
        if self.service_account_json:
            return "service_account"
        return "unconfigured"

    @property
    def is_configured(self) -> bool:
        has_oauth = bool(self.client_id and self.client_secret and self.refresh_token)
        has_sa = bool(self.service_account_json)
        return bool(self.folder_id and (has_oauth or has_sa))

    @property
    def reauthorization_required(self) -> bool:
        return self._reauthorization_required

    @property
    def last_auth_error(self) -> str | None:
        return self._last_auth_error

    def _is_permanent_auth_error(self, exc: Exception) -> bool:
        """Determine if an exception represents a permanent, non-recoverable OAuth failure."""
        try:
            from google.auth.exceptions import RefreshError
            if isinstance(exc, RefreshError):
                err_str = str(exc).lower()
                if any(term in err_str for term in ("invalid_grant", "invalid_client", "unauthorized_client")):
                    return True
        except ImportError:
            pass

        try:
            from googleapiclient.errors import HttpError
            if isinstance(exc, HttpError) and exc.resp.status == 401:
                err_str = str(exc).lower()
                if any(term in err_str for term in ("invalid_grant", "revoked", "expired", "invalid_token")):
                    return True
        except ImportError:
            pass

        err_str = str(exc).lower()
        if "invalid_grant" in err_str:
            return True

        return False

    def _is_retryable_error(self, exc: Exception) -> bool:
        """Determine if an exception represents a transient failure that should be retried."""
        if self._is_permanent_auth_error(exc):
            return False

        try:
            from googleapiclient.errors import HttpError
            if isinstance(exc, HttpError):
                return exc.resp.status in (429, 500, 502, 503, 504)
        except ImportError:
            pass

        if isinstance(exc, (TimeoutError, ConnectionError, socket.timeout, ssl.SSLError)):
            return True

        err_msg = str(exc).lower()
        if any(term in err_msg for term in ("timeout", "connection reset", "connection refused", "temporarily unavailable", "rate limit")):
            return True

        return False

    def _get_credentials(self) -> Any:
        if self._credentials is not None:
            return self._credentials

        credentials = None

        if self.refresh_token:
            from google.oauth2.credentials import Credentials

            credentials = Credentials(
                token=None,
                refresh_token=self.refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=self.client_id,
                client_secret=self.client_secret,
                scopes=self.SCOPES,
            )
        elif self.service_account_json:
            from google.oauth2.service_account import Credentials

            if self.service_account_json.startswith("{"):
                info = json.loads(self.service_account_json)
                credentials = Credentials.from_service_account_info(info, scopes=self.SCOPES)
            else:
                credentials = Credentials.from_service_account_file(
                    self.service_account_json, scopes=self.SCOPES
                )

        if credentials is None:
            raise StorageAuthenticationError(
                "Google Drive storage is not configured. Provide GOOGLE_DRIVE_FOLDER_ID and "
                "either OAuth2 credentials (CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN) or "
                "GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON."
            )

        self._credentials = credentials
        return self._credentials

    def refresh_access_token(self) -> str | None:
        """Explicitly refresh the OAuth2 access token in a thread-safe manner."""
        with self._lock:
            creds = self._get_credentials()
            from google.auth.transport.requests import Request
            from google.auth.exceptions import RefreshError

            try:
                creds.refresh(Request())
                self._reauthorization_required = False
                self._last_auth_error = None
                return creds.token
            except RefreshError as exc:
                if self._is_permanent_auth_error(exc):
                    self._reauthorization_required = True
                    self._last_auth_error = "invalid_grant: Token has been expired or revoked"
                    logger.error(
                        "gdrive_permanent_auth_failure",
                        error="invalid_grant",
                        message="Google OAuth refresh token expired or revoked. Reauthorization required.",
                    )
                    raise StorageAuthenticationError(
                        "Google Drive storage requires reauthorization. The OAuth refresh token has expired or been revoked."
                    ) from exc
                logger.warning("gdrive_refresh_transient_failure", error=str(exc))
                raise

    def check_status(self) -> dict[str, Any]:
        """Return safe, non-sensitive diagnostic status for administrative inspection."""
        return {
            "backend": "gdrive",
            "configured": self.is_configured,
            "auth_mode": self.auth_mode,
            "has_folder_id": bool(self.folder_id),
            "reauthorization_required": self._reauthorization_required,
            "last_auth_error": self._last_auth_error,
        }

    def _get_drive_service(self) -> Any:
        if self._drive_service is not None:
            return self._drive_service

        if self._reauthorization_required:
            raise StorageAuthenticationError(
                "Google Drive storage requires reauthorization. The OAuth refresh token has expired or been revoked."
            )

        with self._lock:
            if self._drive_service is not None:
                return self._drive_service

            credentials = self._get_credentials()
            from googleapiclient.discovery import build

            self._drive_service = build("drive", "v3", credentials=credentials, cache_discovery=False)
            return self._drive_service

    def upload_file(
        self,
        data: bytes,
        original_name: str,
        storage_key: str,
        content_type: str = "application/octet-stream",
    ) -> tuple[str, str]:
        """Upload file bytes to Google Drive within the designated private folder.

        Returns (drive_file_id, effective_storage_key).
        """
        if self._reauthorization_required:
            raise StorageAuthenticationError(
                "Google Drive storage requires reauthorization. The OAuth refresh token has expired or been revoked."
            )

        from googleapiclient.http import MediaIoBaseUpload

        drive = self._get_drive_service()
        safe_drive_name = storage_key.replace("/", "_")
        sha256 = hashlib.sha256(data).hexdigest()

        file_metadata: dict[str, Any] = {
            "name": safe_drive_name,
            "parents": [self.folder_id],
            "appProperties": {
                "storage_key": storage_key,
                "original_name": original_name,
                "sha256": sha256,
            },
        }

        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=content_type, resumable=True)

        last_err: Exception | None = None
        for attempt in range(1, 4):
            try:
                created = (
                    drive.files()
                    .create(
                        body=file_metadata,
                        media_body=media,
                        fields="id, name, size",
                        supportsAllDrives=True,
                    )
                    .execute()
                )
                file_id = created.get("id")
                if not file_id:
                    raise StorageUploadError("Google Drive API did not return a file ID")
                effective_key = f"gdrive/{file_id}/{original_name or Path(storage_key).name}"
                logger.info(
                    "file_persisted_to_gdrive",
                    drive_file_id=file_id,
                    storage_key=effective_key,
                    folder_id=self.folder_id,
                )
                return file_id, effective_key
            except Exception as e:
                last_err = e
                # Permanent auth failure: fail fast immediately without futile retries
                if self._is_permanent_auth_error(e):
                    self._reauthorization_required = True
                    self._last_auth_error = "invalid_grant: Token has been expired or revoked"
                    logger.error(
                        "gdrive_permanent_auth_failure",
                        attempt=attempt,
                        error="invalid_grant",
                        storage_key=storage_key,
                        message="Google OAuth refresh token expired or revoked. Halting retries.",
                    )
                    raise StorageAuthenticationError(
                        "Google Drive storage requires reauthorization. The OAuth refresh token has expired or been revoked."
                    ) from e

                # Non-retryable error
                if not self._is_retryable_error(e):
                    logger.error(
                        "gdrive_upload_non_retryable_error",
                        attempt=attempt,
                        error=str(e),
                        storage_key=storage_key,
                    )
                    raise StorageUploadError(f"Failed to upload file to Google Drive: {e}") from e

                logger.warning(
                    "gdrive_upload_transient_attempt_failed",
                    attempt=attempt,
                    error=str(e),
                    storage_key=storage_key,
                )
                if attempt < 3:
                    time.sleep(1.0 * attempt)

        raise StorageUploadError(
            f"Failed to upload file to Google Drive after 3 attempts: {last_err}"
        ) from last_err

    def _resolve_file_id(self, storage_key: str) -> str | None:
        """Extract or look up the Google Drive file ID from a storage key."""
        if storage_key.startswith("gdrive/"):
            parts = storage_key.split("/", 2)
            if len(parts) >= 2 and parts[1]:
                return parts[1]

        # Legacy or non-standard key: search by name in folder
        try:
            drive = self._get_drive_service()
            safe_name = storage_key.replace("/", "_")
            q = f"name = '{safe_name}' and '{self.folder_id}' in parents and trashed = false"
            res = (
                drive.files()
                .list(
                    q=q,
                    fields="files(id, name)",
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
            files = res.get("files", [])
            if files:
                return str(files[0]["id"])
        except Exception:
            logger.warning("gdrive_lookup_failed", storage_key=storage_key, exc_info=True)

        return None

    def download_file(self, storage_key: str, destination_path: Path) -> StorageResult | Path | None:
        """Download file from Google Drive to local destination path."""
        if self._reauthorization_required:
            logger.error("gdrive_download_blocked_reauth_required", storage_key=storage_key)
            return None

        from googleapiclient.http import MediaIoBaseDownload

        file_id = self._resolve_file_id(storage_key)
        if not file_id:
            logger.warning("gdrive_file_id_not_found", storage_key=storage_key)
            return None

        drive = self._get_drive_service()
        destination_path.parent.mkdir(parents=True, exist_ok=True)

        last_err: Exception | None = None
        for attempt in range(1, 4):
            try:
                request = drive.files().get_media(fileId=file_id, supportsAllDrives=True)
                with open(destination_path, "wb") as f:
                    downloader = MediaIoBaseDownload(f, request)
                    done = False
                    while not done:
                        _, done = downloader.next_chunk()

                logger.info(
                    "file_restored_from_gdrive",
                    drive_file_id=file_id,
                    storage_key=storage_key,
                    destination=str(destination_path),
                )
                return StorageResult(destination_path, storage_key=storage_key, drive_file_id=file_id)
            except Exception as e:
                last_err = e
                if destination_path.exists():
                    destination_path.unlink(missing_ok=True)

                if self._is_permanent_auth_error(e):
                    self._reauthorization_required = True
                    self._last_auth_error = "invalid_grant: Token has been expired or revoked"
                    logger.error("gdrive_permanent_auth_failure_on_download", error="invalid_grant")
                    return None

                if not self._is_retryable_error(e):
                    logger.error("gdrive_download_non_retryable_error", error=str(e))
                    return None

                logger.warning(
                    "gdrive_download_attempt_failed",
                    attempt=attempt,
                    drive_file_id=file_id,
                    error=str(e),
                )
                if attempt < 3:
                    time.sleep(1.0 * attempt)

        logger.error(
            "gdrive_download_failed",
            drive_file_id=file_id,
            error=str(last_err),
            exc_info=True,
        )
        return None

    def file_exists(self, storage_key: str) -> bool:
        """Check if file exists on Google Drive."""
        file_id = self._resolve_file_id(storage_key)
        if not file_id:
            return False
        try:
            drive = self._get_drive_service()
            res = (
                drive.files()
                .get(fileId=file_id, fields="id, trashed", supportsAllDrives=True)
                .execute()
            )
            return not res.get("trashed", False)
        except Exception:
            return False

    def delete_file(self, storage_key: str) -> None:
        """Delete file from Google Drive."""
        file_id = self._resolve_file_id(storage_key)
        if not file_id:
            return
        try:
            drive = self._get_drive_service()
            drive.files().delete(fileId=file_id, supportsAllDrives=True).execute()
            logger.info("file_deleted_from_gdrive", drive_file_id=file_id)
        except Exception:
            logger.warning("gdrive_delete_failed", drive_file_id=file_id, exc_info=True)


class StorageService:
    def __init__(self) -> None:
        self.backend = (upload_settings.storage_backend or "local").lower()
        self.local_root = Path(upload_settings.local_storage_root).resolve()
        self.local_root.mkdir(parents=True, exist_ok=True)
        self._s3_client: Any = None
        self._gdrive_storage: GoogleDriveStorage | None = None

    @property
    def gdrive(self) -> GoogleDriveStorage:
        if self._gdrive_storage is None:
            self._gdrive_storage = GoogleDriveStorage(self.local_root)
        return self._gdrive_storage

    @property
    def is_gdrive_enabled(self) -> bool:
        return self.backend in ("gdrive", "googledrive")

    @property
    def is_s3_enabled(self) -> bool:
        return self.backend in ("s3", "r2") and bool(
            upload_settings.s3_bucket_name
            and upload_settings.s3_access_key_id
            and upload_settings.s3_secret_access_key
        )

    def _get_s3_client(self) -> Any:
        if self._s3_client is None:
            import boto3
            from botocore.config import Config

            client_kwargs: dict[str, Any] = {
                "service_name": "s3",
                "aws_access_key_id": upload_settings.s3_access_key_id,
                "aws_secret_access_key": upload_settings.s3_secret_access_key,
                "region_name": upload_settings.s3_region_name or "auto",
                "config": Config(signature_version="s3v4", s3={"addressing_style": "path"}),
            }
            if upload_settings.s3_endpoint_url:
                client_kwargs["endpoint_url"] = upload_settings.s3_endpoint_url

            self._s3_client = boto3.client(**client_kwargs)
        return self._s3_client

    def _resolve_safe_local_path(self, storage_key: str) -> Path:
        resolved = (self.local_root / storage_key).resolve()
        if not str(resolved).startswith(str(self.local_root)):
            raise ValueError(f"Path traversal detected for storage key: {storage_key}")
        return resolved

    def save_file(
        self,
        storage_key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        original_name: str | None = None,
    ) -> StorageResult:
        """Save file bytes locally and sync to configured cloud storage (Google Drive or S3).

        Returns a StorageResult object delegating to Path while exposing storage_key
        and drive_file_id.
        """
        local_path = self._resolve_safe_local_path(storage_key)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(data)

        effective_storage_key = storage_key
        drive_file_id: str | None = None

        if self.is_gdrive_enabled:
            is_prod = os.environ.get("APP_ENV", "").strip().lower() in ("production", "staging", "prod")
            if not self.gdrive.is_configured:
                if is_prod:
                    raise StorageAuthenticationError(
                        "Production STORAGE_BACKEND=gdrive is configured but Google Drive credentials or "
                        "folder ID are missing. Ephemeral fallback is strictly forbidden in production."
                    )
                logger.warning("gdrive_unconfigured_skipping_remote_sync", storage_key=storage_key)
            else:
                try:
                    drive_file_id, effective_storage_key = self.gdrive.upload_file(
                        data=data,
                        original_name=original_name or Path(storage_key).name,
                        storage_key=storage_key,
                        content_type=content_type,
                    )
                    gdrive_local_path = self._resolve_safe_local_path(effective_storage_key)
                    if gdrive_local_path != local_path:
                        gdrive_local_path.parent.mkdir(parents=True, exist_ok=True)
                        try:
                            import shutil
                            shutil.copy2(local_path, gdrive_local_path)
                        except Exception:
                            with open(gdrive_local_path, "wb") as f:
                                f.write(data)
                        local_path = gdrive_local_path
                except Exception:
                    if local_path.exists():
                        local_path.unlink(missing_ok=True)
                    raise

        elif self.is_s3_enabled:
            try:
                s3 = self._get_s3_client()
                s3.put_object(
                    Bucket=upload_settings.s3_bucket_name,
                    Key=storage_key,
                    Body=data,
                    ContentType=content_type,
                )
                logger.info(
                    "file_persisted_to_s3",
                    bucket=upload_settings.s3_bucket_name,
                    key=storage_key,
                )
            except Exception:
                logger.error("s3_upload_failed", key=storage_key, exc_info=True)
                if local_path.exists():
                    local_path.unlink(missing_ok=True)
                raise

        return StorageResult(
            path=local_path,
            storage_key=effective_storage_key,
            drive_file_id=drive_file_id,
        )

    def get_file_path(self, storage_key: str) -> StorageResult | Path | None:
        """Get local Path to file, fetching from Google Drive or S3 if missing locally."""
        try:
            local_path = self._resolve_safe_local_path(storage_key)
        except ValueError:
            return None

        if local_path.exists():
            drive_file_id = None
            if storage_key.startswith("gdrive/"):
                parts = storage_key.split("/", 2)
                if len(parts) >= 2:
                    drive_file_id = parts[1]
            return StorageResult(local_path, storage_key=storage_key, drive_file_id=drive_file_id)

        # If missing locally and Google Drive is configured:
        # Fetch from Drive if gdrive is enabled OR if the key is explicitly a gdrive key (enables safe rollback)
        is_gdrive_key = storage_key.startswith("gdrive/")
        if self.is_gdrive_enabled or is_gdrive_key:
            is_prod = os.environ.get("APP_ENV", "").strip().lower() in ("production", "staging", "prod")
            if not self.gdrive.is_configured:
                if is_prod and self.is_gdrive_enabled:
                    raise StorageAuthenticationError(
                        "Production STORAGE_BACKEND=gdrive is configured but Google Drive credentials "
                        "are missing. Cannot restore document."
                    )
                logger.warning("gdrive_unconfigured_skipping_remote_download", storage_key=storage_key)
                return None

            return self.gdrive.download_file(storage_key, local_path)

        # If missing locally and S3 is configured, fetch from S3
        is_s3_key = storage_key.startswith("s3/")
        if self.is_s3_enabled or is_s3_key:
            try:
                s3 = self._get_s3_client()
                local_path.parent.mkdir(parents=True, exist_ok=True)
                s3.download_file(
                    Bucket=upload_settings.s3_bucket_name,
                    Key=storage_key,
                    Filename=str(local_path),
                )
                logger.info(
                    "file_restored_from_s3",
                    bucket=upload_settings.s3_bucket_name,
                    key=storage_key,
                )
                return StorageResult(local_path, storage_key=storage_key)
            except Exception:
                logger.warning("s3_download_failed", key=storage_key, exc_info=True)
                if local_path.exists():
                    local_path.unlink(missing_ok=True)

        return None

    def file_exists(self, storage_key: str) -> bool:
        """Check if file exists locally or in Google Drive / S3."""
        try:
            local_path = self._resolve_safe_local_path(storage_key)
            if local_path.exists():
                return True
        except ValueError:
            return False

        is_gdrive_key = storage_key.startswith("gdrive/")
        if (self.is_gdrive_enabled or is_gdrive_key) and self.gdrive.is_configured:
            return self.gdrive.file_exists(storage_key)

        is_s3_key = storage_key.startswith("s3/")
        if (self.is_s3_enabled or is_s3_key) and self.is_s3_enabled:
            try:
                s3 = self._get_s3_client()
                s3.head_object(
                    Bucket=upload_settings.s3_bucket_name,
                    Key=storage_key,
                )
                return True
            except Exception:
                return False

        return False

    def delete_file(self, storage_key: str) -> None:
        """Delete file locally and from Google Drive / S3."""
        try:
            local_path = self._resolve_safe_local_path(storage_key)
            if local_path.exists():
                local_path.unlink()
        except Exception:
            logger.warning("local_delete_failed", key=storage_key, exc_info=True)

        is_gdrive_key = storage_key.startswith("gdrive/")
        if (self.is_gdrive_enabled or is_gdrive_key) and self.gdrive.is_configured:
            self.gdrive.delete_file(storage_key)

        if self.is_s3_enabled:
            try:
                s3 = self._get_s3_client()
                s3.delete_object(
                    Bucket=upload_settings.s3_bucket_name,
                    Key=storage_key,
                )
            except Exception:
                logger.warning("s3_delete_failed", key=storage_key, exc_info=True)


_storage_service: StorageService | None = None


def get_storage_service() -> StorageService:
    global _storage_service
    if _storage_service is None:
        _storage_service = StorageService()
    return _storage_service


def reset_storage_service() -> None:
    global _storage_service
    _storage_service = None

