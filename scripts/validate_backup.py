#!/usr/bin/env python3
"""Validate the integrity of the database backup file."""
import hashlib
import json
from pathlib import Path

import sys

if len(sys.argv) > 1:
    backup_path = Path(sys.argv[1])
else:
    backup_files = sorted(Path("scripts").glob("db_full_backup_*.json"))
    backup_path = backup_files[-1] if backup_files else Path("scripts/db_full_backup_20261018_153905.json")

if not backup_path.exists():
    print(f"Backup file not found: {backup_path}")
    exit(1)

# SHA-256
hasher = hashlib.sha256()
with open(backup_path, "rb") as f:
    while chunk := f.read(65536):
        hasher.update(chunk)
calc_sha = hasher.hexdigest()

with open(backup_path, "r", encoding="utf-8") as f:
    data = json.load(f)

print("=" * 70)
print("  DATABASE BACKUP VALIDATION REPORT")
print("=" * 70)
print(f"File Path:       {backup_path}")
print(f"File Size:       {backup_path.stat().st_size / 1024.0:.2f} KB")
print(f"Calculated SHA:  {calc_sha}")
print(f"Created At:      {data.get('created_at')}")
print(f"Target DB:       {data.get('database')}")
print(f"Tables in File:  {len(data.get('tables', {}))}")
total_rows = sum(len(rows) for rows in data.get("tables", {}).values())
print(f"Total Rows:      {total_rows}")
print("-" * 70)
print("Row Breakdown:")
for tbl, count in sorted(data.get("table_counts", {}).items()):
    print(f"  {tbl:<28}: {count} rows")
print("=" * 70)
