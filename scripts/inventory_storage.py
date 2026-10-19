#!/usr/bin/env python3
"""Read-only document and storage inventory utility for FPP.

Strictly non-destructive:
- Executes ONLY read-only SELECT queries against the database.
- Inspects storage keys and local filesystem existence.
- Detects already-migrated vs unmigrated files.
- Identifies missing physical files on disk.
- Never modifies, updates, or deletes database records or files.
- Never prints or exposes credentials or sensitive patent content.

Usage:
    python scripts/inventory_storage.py
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from collections import Counter
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from sqlalchemy import func, select

from app.core.config import upload_settings
from app.core.database import get_session
from app.models.base import IpFile, IpRecord
from app.services.storage import StorageService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("storage_inventory")


def run_inventory() -> dict[str, object]:
    session = get_session()
    service = StorageService()

    report: dict[str, object] = {
        "storage_backend_setting": upload_settings.storage_backend,
        "local_storage_root": str(service.local_root),
        "total_ip_records": 0,
        "total_ip_files": 0,
        "by_storage_backend": {},
        "files_accessible_locally": 0,
        "files_missing_locally": 0,
        "files_requiring_migration": 0,
        "already_on_gdrive": 0,
        "checksum_verified_locally": 0,
        "checksum_mismatch_locally": 0,
        "duplicate_fingerprints_count": 0,
    }

    try:
        # 1. Total counts
        total_records = session.execute(select(func.count(IpRecord.id))).scalar() or 0
        total_files = session.execute(select(func.count(IpFile.id))).scalar() or 0
        report["total_ip_records"] = total_records
        report["total_ip_files"] = total_files

        # 2. Inspect all file records
        file_rows = session.execute(
            select(
                IpFile.id,
                IpFile.storage_key,
                IpFile.file_size_bytes,
                IpFile.fingerprint,
                IpFile.created_at,
            ).order_by(IpFile.created_at.asc())
        ).all()

        backend_counts: Counter[str] = Counter()
        fingerprints: Counter[str] = Counter()

        accessible_locally = 0
        missing_locally = 0
        requiring_migration = 0
        already_gdrive = 0
        checksum_verified = 0
        checksum_mismatch = 0

        for row in file_rows:
            file_id, storage_key, size_bytes, fingerprint, created_at = row
            key = storage_key or ""

            if fingerprint:
                fingerprints[fingerprint] += 1

            if key.startswith("gdrive/"):
                backend_counts["gdrive"] += 1
                already_gdrive += 1
            elif key.startswith("s3/"):
                backend_counts["s3"] += 1
            else:
                backend_counts["local"] += 1
                requiring_migration += 1

            # Check physical presence in local storage root
            try:
                local_path = service._resolve_safe_local_path(key)
                if local_path.is_file():
                    accessible_locally += 1
                    if fingerprint:
                        local_sha = hashlib.sha256(local_path.read_bytes()).hexdigest()
                        if local_sha == fingerprint:
                            checksum_verified += 1
                        else:
                            checksum_mismatch += 1
                else:
                    missing_locally += 1
            except Exception:
                missing_locally += 1

        report["by_storage_backend"] = dict(backend_counts)
        report["already_on_gdrive"] = already_gdrive
        report["files_requiring_migration"] = requiring_migration
        report["files_accessible_locally"] = accessible_locally
        report["files_missing_locally"] = missing_locally
        report["checksum_verified_locally"] = checksum_verified
        report["checksum_mismatch_locally"] = checksum_mismatch
        report["duplicate_fingerprints_count"] = sum(1 for count in fingerprints.values() if count > 1)

    finally:
        session.close()

    return report


def main() -> None:
    print("=" * 70)
    print("  Faculty Patent Portal (FPP) - Read-Only Storage Inventory")
    print("=" * 70)

    try:
        data = run_inventory()
    except Exception as e:
        print(f"\nERROR: Failed to connect to database for inventory: {e}")
        print("Inventory status: NOT VERIFIED")
        sys.exit(1)

    print(f"\nActive STORAGE_BACKEND:       {data['storage_backend_setting']}")
    print(f"Local Storage Root:           {data['local_storage_root']}")
    print("-" * 70)
    print(f"Total Patent Records:         {data['total_ip_records']}")
    print(f"Total Document Files:         {data['total_ip_files']}")
    print(f"Storage Breakdown:            {data['by_storage_backend']}")
    print(f"  - Already on Google Drive:  {data['already_on_gdrive']}")
    print(f"  - Requiring Migration:      {data['files_requiring_migration']}")
    print("-" * 70)
    print(f"Local File Presence on this host:")
    print(f"  - Present on local disk:    {data['files_accessible_locally']}")
    print(f"  - Missing from local disk:  {data['files_missing_locally']}")
    print(f"  - SHA-256 Checksum Verified:{data['checksum_verified_locally']}")
    print(f"  - Checksum Mismatches:      {data['checksum_mismatch_locally']}")
    print(f"Duplicate Fingerprints:       {data['duplicate_fingerprints_count']}")
    print("=" * 70)


if __name__ == "__main__":
    main()
