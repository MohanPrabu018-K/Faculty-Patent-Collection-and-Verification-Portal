#!/usr/bin/env python3
"""Full database snapshot utility for FPP clean reset.

Strict safety constraints:
- Strictly READ-ONLY against the database.
- Backs up all tables and records into a serialized, timestamped JSON snapshot.
- Computes SHA-256 checksum to guarantee data integrity.
- Never prints secrets to stdout.
- Output file is strictly git-ignored.
"""
from __future__ import annotations

import datetime
import decimal
import hashlib
import json
import sys
import uuid
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from sqlalchemy import inspect, select, text
from app.core.database import sync_engine


class CustomEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime.datetime, datetime.date, datetime.time)):
            return obj.isoformat()
        if isinstance(obj, uuid.UUID):
            return str(obj)
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        if isinstance(obj, bytes):
            return obj.hex()
        return super().default(obj)


def create_full_backup(output_path: Path | None = None) -> Path:
    if output_path is None:
        timestamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d_%H%M%S")
        output_path = Path(__file__).resolve().parent / f"db_full_backup_{timestamp}.json"

    print("=" * 70)
    print("  FPP FULL DATABASE BACKUP UTILITY (PRE-RESET)")
    print("=" * 70)

    inspector = inspect(sync_engine)
    table_names = sorted(inspector.get_table_names())
    print(f"Total tables to back up: {len(table_names)}\n")

    snapshot_data: dict[str, object] = {
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "database": "neondb",
        "tables": {},
        "table_counts": {},
    }

    total_rows = 0

    with sync_engine.connect() as conn:
        for tbl in table_names:
            rows = conn.execute(text(f'SELECT * FROM "{tbl}"')).mappings().all()
            serialized_rows = [dict(r) for r in rows]
            snapshot_data["tables"][tbl] = serialized_rows
            snapshot_data["table_counts"][tbl] = len(serialized_rows)
            total_rows += len(serialized_rows)
            print(f"  Backed up {tbl:<28}: {len(serialized_rows)} rows")

    print("-" * 70)
    print(f"Total rows backed up across all tables: {total_rows}")

    # Write to file
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(snapshot_data, f, indent=2, cls=CustomEncoder)

    # Compute checksum
    hasher = hashlib.sha256()
    with open(output_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    checksum = hasher.hexdigest()

    file_size_kb = output_path.stat().st_size / 1024.0

    print(f"Backup file written to: {output_path}")
    print(f"Backup file size:       {file_size_kb:.2f} KB")
    print(f"Backup SHA-256 Checksum:{checksum}")
    print("=" * 70)

    return output_path


if __name__ == "__main__":
    create_full_backup()
