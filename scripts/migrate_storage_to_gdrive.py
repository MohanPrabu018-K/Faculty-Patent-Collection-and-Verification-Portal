#!/usr/bin/env python3
"""Migration script to transfer existing local documents to Google Drive.

Requirements addressed:
- Uploads local files to designated Google Drive folder.
- Verifies SHA-256 checksum integrity of the uploaded document before committing DB changes.
- Updates IpFile.storage_key and IpRecord.evidence.
- Preserves existing local files by default. Does not delete local files unless
  --cleanup is explicitly provided AND integrity verification passes.
- Supports --dry-run to simulate without modifying database or Drive.

Usage:
    python scripts/migrate_storage_to_gdrive.py --dry-run
    python scripts/migrate_storage_to_gdrive.py
    python scripts/migrate_storage_to_gdrive.py --cleanup
"""
from __future__ import annotations

import argparse
import hashlib
import io
import logging
import sys
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from sqlalchemy import select
from googleapiclient.http import MediaIoBaseDownload

from app.core.config import upload_settings
from app.core.database import get_session
from app.models.base import IpFile, IpRecord
from app.services.storage import GoogleDriveStorage, StorageService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("migrate_to_gdrive")


def calculate_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download_bytes_from_drive(drive_service, file_id: str) -> bytes:
    """Download full file bytes from Google Drive in-memory for integrity verification."""
    request = drive_service.files().get_media(fileId=file_id, supportsAllDrives=True)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


def run_migration(dry_run: bool = False, cleanup: bool = False, limit: int | None = None) -> dict[str, int]:
    service = StorageService()
    gdrive: GoogleDriveStorage = service.gdrive

    if not gdrive.is_configured:
        logger.error(
            "Google Drive storage is not configured! Set GOOGLE_DRIVE_FOLDER_ID, "
            "GOOGLE_DRIVE_CLIENT_ID, GOOGLE_DRIVE_CLIENT_SECRET, and GOOGLE_DRIVE_REFRESH_TOKEN "
            "(or GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON)."
        )
        sys.exit(1)

    logger.info("Initializing Google Drive API client (auth_mode=%s)...", gdrive.auth_mode)
    drive_api = gdrive._get_drive_service()

    session = get_session()
    stats = {"scanned": 0, "already_migrated": 0, "migrated": 0, "missing_local": 0, "failed": 0}

    try:
        query = select(IpFile).order_by(IpFile.created_at.asc())
        if limit:
            query = query.limit(limit)
        files = session.execute(query).scalars().all()
        stats["scanned"] = len(files)

        logger.info("Found %d IpFile records in database.", len(files))

        for ip_file in files:
            storage_key = ip_file.storage_key
            if not storage_key:
                continue

            if storage_key.startswith("gdrive/"):
                stats["already_migrated"] += 1
                continue

            # Resolve local file
            try:
                local_path = service._resolve_safe_local_path(storage_key)
            except ValueError:
                logger.warning("Unsafe storage key '%s' on IpFile %s, skipping.", storage_key, ip_file.id)
                stats["failed"] += 1
                continue

            if not local_path.exists() or not local_path.is_file():
                logger.warning("Local file not found for key '%s' (path: %s)", storage_key, local_path)
                stats["missing_local"] += 1
                continue

            local_bytes = local_path.read_bytes()
            local_sha256 = calculate_sha256(local_bytes)
            file_name = ip_file.original_filename or local_path.name
            mime_type = ip_file.mime_type or "application/octet-stream"

            logger.info(
                "Migrating [%s] %s (%d bytes, sha256=%s...)",
                ip_file.id,
                file_name,
                len(local_bytes),
                local_sha256[:12],
            )

            if dry_run:
                logger.info("[DRY-RUN] Would upload %s to Google Drive folder %s", file_name, gdrive.folder_id)
                stats["migrated"] += 1
                continue

            try:
                # 1. Upload to Google Drive
                drive_file_id, effective_key = gdrive.upload_file(
                    data=local_bytes,
                    original_name=file_name,
                    storage_key=storage_key,
                    content_type=mime_type,
                )

                # 2. Strict SHA-256 Integrity Verification
                logger.info("Verifying integrity of uploaded file (id=%s)...", drive_file_id)
                remote_bytes = download_bytes_from_drive(drive_api, drive_file_id)
                remote_sha256 = calculate_sha256(remote_bytes)

                if remote_sha256 != local_sha256:
                    raise ValueError(
                        f"Checksum mismatch after upload! Local: {local_sha256}, Remote: {remote_sha256}"
                    )

                logger.info("Integrity verified (SHA-256 match). Updating database...")

                # 3. Update database record
                ip_file.storage_key = effective_key
                if not ip_file.fingerprint:
                    ip_file.fingerprint = local_sha256

                if ip_file.ip_record_id:
                    ip_record = session.execute(
                        select(IpRecord).where(IpRecord.id == ip_file.ip_record_id)
                    ).scalar_one_or_none()
                    if ip_record:
                        evidence = dict(ip_record.evidence or {})
                        evidence["drive_file_id"] = drive_file_id
                        evidence["storage_backend"] = "gdrive"
                        ip_record.evidence = evidence

                session.commit()
                stats["migrated"] += 1
                logger.info("Successfully migrated IpFile %s -> %s", ip_file.id, effective_key)

                # 4. Optional cleanup only after verification succeeded
                if cleanup:
                    local_path.unlink(missing_ok=True)
                    logger.info("Cleaned up local file: %s", local_path)

            except Exception as e:
                session.rollback()
                logger.error("Failed to migrate file %s: %s", storage_key, e, exc_info=True)
                stats["failed"] += 1

    finally:
        session.close()

    logger.info("=== Migration Summary ===")
    logger.info("Total Scanned:      %d", stats["scanned"])
    logger.info("Already Migrated:   %d", stats["already_migrated"])
    logger.info("Newly Migrated:     %d", stats["migrated"])
    logger.info("Missing Local File: %d", stats["missing_local"])
    logger.info("Failed:             %d", stats["failed"])
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate local FPP document storage to Google Drive.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate migration without modifying Google Drive or the database.",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Delete local file copies after successful upload and integrity verification.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of files to process.",
    )
    args = parser.parse_args()

    run_migration(dry_run=args.dry_run, cleanup=args.cleanup, limit=args.limit)


if __name__ == "__main__":
    main()
