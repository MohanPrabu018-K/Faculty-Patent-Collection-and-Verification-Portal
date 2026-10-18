"""Persistent Storage Service for FPP.

Supports:
1. Local filesystem storage (default, used for dev/tests).
2. S3-compatible cloud storage (Cloudflare R2, AWS S3) for zero-data-loss
   persistence on free-tier containers with ephemeral disks (Render, Fly, etc.).

When S3/R2 is enabled:
- Saves files locally and pushes to the S3/R2 bucket.
- Downloads from S3/R2 on-demand if the local ephemeral disk was wiped (e.g. after container restart).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, BinaryIO

from app.core.config import upload_settings

logger = logging.getLogger(__name__)


class StorageService:
    def __init__(self) -> None:
        self.backend = (upload_settings.storage_backend or "local").lower()
        self.local_root = Path(upload_settings.local_storage_root).resolve()
        self.local_root.mkdir(parents=True, exist_ok=True)
        self._s3_client: Any = None

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
    ) -> Path:
        """Save file bytes locally and sync to S3/R2 if configured."""
        local_path = self._resolve_safe_local_path(storage_key)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(data)

        if self.is_s3_enabled:
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

        return local_path

    def get_file_path(self, storage_key: str) -> Path | None:
        """Get local Path to file, fetching from S3/R2 if missing locally."""
        try:
            local_path = self._resolve_safe_local_path(storage_key)
        except ValueError:
            return None

        if local_path.exists():
            return local_path

        # If missing locally and S3 is configured, fetch from S3/R2
        if self.is_s3_enabled:
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
                return local_path
            except Exception:
                logger.warning("s3_download_failed", key=storage_key, exc_info=True)
                if local_path.exists():
                    local_path.unlink(missing_ok=True)

        return None

    def file_exists(self, storage_key: str) -> bool:
        """Check if file exists locally or in S3/R2."""
        try:
            local_path = self._resolve_safe_local_path(storage_key)
            if local_path.exists():
                return True
        except ValueError:
            return False

        if self.is_s3_enabled:
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
        """Delete file locally and from S3/R2."""
        try:
            local_path = self._resolve_safe_local_path(storage_key)
            if local_path.exists():
                local_path.unlink()
        except Exception:
            logger.warning("local_delete_failed", key=storage_key, exc_info=True)

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
