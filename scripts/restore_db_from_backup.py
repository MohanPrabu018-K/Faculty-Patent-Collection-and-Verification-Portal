#!/usr/bin/env python3
"""Database restoration utility from JSON backup for FPP.

Strict safety constraints:
- Dry-run by default: does not modify database unless --execute is explicitly supplied.
- Never prints passwords or credentials.
- Restores in dependency-safe order (parents before children).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from sqlalchemy import inspect, text
from app.core.database import sync_engine

# Dependency-safe insertion order (parents first)
TABLE_INSERTION_ORDER = [
    "department",
    "designation",
    "user",
    "master_ip_record",
    "master_ip_contributor",
    "external_contributor",
    "ip_record",
    "ip_file",
    "ip_contributor",
    "faculty_ip_association",
    "processing_job",
    "verification_attempt",
    "master_verification_attempt",
    "field_provenance",
    "association_request",
    "duplicate_case",
    "conflict_case",
    "identity_conflict",
    "faculty_profile_snapshot",
    "notification",
    "security_event",
    "audit_log",
    "rate_limit_state",
    "alembic_version",
]


def restore_backup(backup_file: Path, execute: bool = False, target_table: str | None = None):
    print("=" * 70)
    print("  FPP DATABASE RESTORATION UTILITY")
    print("=" * 70)
    print(f"Backup File:    {backup_file}")
    print(f"Execution Mode: {'LIVE RESTORE' if execute else 'DRY RUN ONLY'}")
    if target_table:
        print(f"Target Table:   {target_table}")
    print("-" * 70)

    if not backup_file.exists():
        print(f"ERROR: Backup file does not exist: {backup_file}")
        return 1

    with open(backup_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    tables_in_backup = data.get("tables", {})
    tables_to_restore = [target_table] if target_table else TABLE_INSERTION_ORDER

    with sync_engine.connect() as conn:
        for tbl in tables_to_restore:
            if tbl not in tables_in_backup:
                continue
            rows = tables_in_backup[tbl]
            print(f"  Table: {tbl:<28} | Rows in backup: {len(rows)}")

            if execute and rows:
                with conn.begin():
                    for row in rows:
                        clean_row = {}
                        for k, v in row.items():
                            if isinstance(v, (dict, list)):
                                clean_row[k] = json.dumps(v)
                            else:
                                clean_row[k] = v
                        cols = list(clean_row.keys())
                        placeholders = ", ".join([f":{c}" for c in cols])
                        col_names = ", ".join([f'"{c}"' for c in cols])
                        stmt = text(f'INSERT INTO "{tbl}" ({col_names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING')
                        conn.execute(stmt, clean_row)

    print("-" * 70)
    if execute:
        print("Restoration complete.")
    else:
        print("Dry run completed. Pass --execute to write to database.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Restore FPP database from JSON backup.")
    parser.add_argument("backup_file", type=Path, help="Path to JSON backup file")
    parser.add_argument("--execute", action="store_true", help="Execute the restore (default is dry-run)")
    parser.add_argument("--table", type=str, default=None, help="Specific table to restore")
    args = parser.parse_args()
    sys.exit(restore_backup(args.backup_file, execute=args.execute, target_table=args.table))
