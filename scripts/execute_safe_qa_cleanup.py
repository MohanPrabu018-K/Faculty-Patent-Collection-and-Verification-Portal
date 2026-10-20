#!/usr/bin/env python3
"""Safe cleanup script for the 3 explicitly authorized QA records.

STRICT CONSTRAINTS:
1. Dry-run by default. Modifies data ONLY when --execute is passed.
2. Safety assertions ensure host is Neon PostgreSQL and DB is neondb.
3. Confirms exactly 19 records before cleanup, and exactly 16 after cleanup.
4. Preserves all 16 baseline records without modification.
5. Deletes only the 3 QA files from Google Drive storage.
6. Preserves audit_log history in accordance with audit retention standards.
7. Checks foreign-key integrity before and after.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from sqlalchemy import text
from app.core.config import database_settings
from app.core.database import sync_session_factory
from app.services.storage import get_storage_service

QA_RECORD_IDS = [
    "1d26ff7a-f817-4367-8ee8-da365eef44b3",
    "5c7bf164-1750-45aa-84e1-7897726fed5d",
    "2c785d72-1864-4968-9468-f0961b540a7c",
]

BASELINE_RECORD_IDS = [
    "51a7d334-f849-474a-acfe-04d80790ab8a",
    "69e637b5-3247-40dd-a85c-97adb2587b05",
    "1323c75d-5773-4e57-be14-e8cf32e1c781",
    "6d82dd6d-7b6a-481d-b408-b8e1ac9412d1",
    "ba61e4e8-4a58-4635-b401-a3f9b1960cc6",
    "0a95f605-8be2-4017-b323-b5f7cca7840f",
    "1856ef33-42f5-4b5f-b24f-51cbceabc1ee",
    "27ab8176-b241-4b29-95a0-f20b79615597",
    "58ee3d7c-386a-403f-9376-c797df980f26",
    "d0070829-3e16-4fd4-98c5-e395a6b3403a",
    "d089ed03-27c9-4215-b051-284df020c668",
    "fb6bf462-f7ec-469e-896d-5bddeb86db5e",
    "82ca0e9c-e54f-45c1-bb2d-245a77b73a92",
    "699ea85d-27c3-47e5-b819-ca74ca63ddfa",
    "db082455-bc8d-4da2-bdd9-a48f7ece3f02",
    "f6b7771e-bcc8-46dc-93b1-ddf839f8aa54",
]

def run_cleanup(execute: bool = False):
    print("=" * 75)
    print("  FPP PRODUCTION QA RECORD CLEANUP")
    print(f"  MODE: {'LIVE EXECUTION' if execute else 'DRY RUN (NO CHANGES)'}")
    print("=" * 75)

    parsed = urlsplit(database_settings.database_url)
    host = parsed.hostname or ""
    db_name = parsed.path.lstrip("/")

    # Guard 1: Verify host & database
    if "neon.tech" not in host or db_name != "neondb":
        print(f"FATAL: Connected to unexpected host/db ({host}/{db_name}). Aborting.")
        return False

    session = sync_session_factory()
    storage_svc = get_storage_service()

    try:
        # Guard 2: Total count & presence
        total_records = session.execute(text("SELECT count(*) FROM ip_record")).scalar()
        print(f"Current total records in DB: {total_records}")
        if total_records != 19:
            print(f"FATAL: Expected exactly 19 records before cleanup, found {total_records}. Aborting.")
            return False

        # Guard 3: Verify all 16 baseline records exist
        baseline_rows = session.execute(
            text("SELECT id, title FROM ip_record WHERE id IN :ids"),
            {"ids": tuple(BASELINE_RECORD_IDS)}
        ).fetchall()
        if len(baseline_rows) != 16:
            print(f"FATAL: Expected all 16 baseline records to be present, found {len(baseline_rows)}. Aborting.")
            return False
        print(f"All 16 baseline records verified present.")

        # Guard 4: Verify the 3 QA records exist
        qa_rows = session.execute(
            text("SELECT id, title, master_ip_id FROM ip_record WHERE id IN :ids"),
            {"ids": tuple(QA_RECORD_IDS)}
        ).fetchall()
        if len(qa_rows) != 3:
            print(f"FATAL: Expected exactly 3 QA records, found {len(qa_rows)}. Aborting.")
            return False

        qa_master_ids = [str(r.master_ip_id) for r in qa_rows if r.master_ip_id]
        print(f"QA records verified:")
        for r in qa_rows:
            print(f"  - [{r.id}] {r.title} (master_ip: {r.master_ip_id})")

        # Guard 5: Verify master_ip_records are not used by baseline
        if qa_master_ids:
            cross_master = session.execute(
                text("SELECT count(*) FROM ip_record WHERE master_ip_id IN :mids AND id NOT IN :qa_ids"),
                {"mids": tuple(qa_master_ids), "qa_ids": tuple(QA_RECORD_IDS)}
            ).scalar()
            if cross_master > 0:
                print(f"FATAL: QA master IP records are referenced by baseline records ({cross_master}). Aborting.")
                return False
            print("Verified: QA master records are exclusively linked to QA records.")

        # Guard 6: Find all QA files
        qa_files = session.execute(
            text("SELECT id, ip_record_id, original_filename, storage_key FROM ip_file WHERE ip_record_id IN :qa_ids"),
            {"qa_ids": tuple(QA_RECORD_IDS)}
        ).fetchall()
        print(f"\nQA files identified for cleanup ({len(qa_files)} files):")
        for f in qa_files:
            print(f"  - File ID: {f.id} | Name: {f.original_filename} | Key: {f.storage_key}")

        # Check storage file existence
        for f in qa_files:
            exists = storage_svc.file_exists(f.storage_key)
            print(f"    Storage exists ({f.storage_key}): {exists}")

        if not execute:
            print("\n[DRY RUN COMPLETE] No data or storage files modified.")
            print("Run with --execute to perform actual cleanup.")
            return True

        # =========================================================================
        # EXECUTION PHASE
        # =========================================================================
        print("\n>>> PROCEEDING WITH SAFE DELETION IN NEON DATABASE AND GOOGLE DRIVE <<<")

        # Step 1: Delete Google Drive files
        print("\n1. Deleting QA files from Google Drive storage...")
        deleted_files_count = 0
        for f in qa_files:
            print(f"   Deleting {f.storage_key}...")
            storage_svc.delete_file(f.storage_key)
            # Recheck
            still_exists = storage_svc.file_exists(f.storage_key)
            if still_exists:
                print(f"   WARNING: File {f.storage_key} still reported existing in storage.")
            else:
                print(f"   SUCCESS: File {f.storage_key} removed from storage.")
                deleted_files_count += 1

        # Step 2: Delete database records in foreign-key safe order
        print("\n2. Deleting QA database rows in foreign-key dependency order...")

        # A. Notification
        del_notif = session.execute(
            text("DELETE FROM notification WHERE related_entity_id IN :ids"),
            {"ids": tuple(QA_RECORD_IDS)}
        ).rowcount
        print(f"   Deleted {del_notif} rows from notification")

        # B. DuplicateCase
        del_dups = session.execute(
            text("DELETE FROM duplicate_case WHERE ip_record_id_1 IN :ids OR ip_record_id_2 IN :ids"),
            {"ids": tuple(QA_RECORD_IDS)}
        ).rowcount
        print(f"   Deleted {del_dups} rows from duplicate_case")

        # C. ConflictCase (by ip_record_id and master_ip_id)
        del_conf = session.execute(
            text("DELETE FROM conflict_case WHERE ip_record_id IN :ids OR (master_ip_id IS NOT NULL AND master_ip_id IN :mids)"),
            {"ids": tuple(QA_RECORD_IDS), "mids": tuple(qa_master_ids) if qa_master_ids else ("none",)}
        ).rowcount
        print(f"   Deleted {del_conf} rows from conflict_case")

        # D. AssociationRequest
        del_assoc = session.execute(
            text("DELETE FROM association_request WHERE ip_record_id IN :ids OR (master_ip_id IS NOT NULL AND master_ip_id IN :mids)"),
            {"ids": tuple(QA_RECORD_IDS), "mids": tuple(qa_master_ids) if qa_master_ids else ("none",)}
        ).rowcount
        print(f"   Deleted {del_assoc} rows from association_request")

        # E. VerificationAttempt
        del_verif = session.execute(
            text("DELETE FROM verification_attempt WHERE ip_record_id IN :ids"),
            {"ids": tuple(QA_RECORD_IDS)}
        ).rowcount
        print(f"   Deleted {del_verif} rows from verification_attempt")

        # F. ProcessingJob
        del_jobs = session.execute(
            text("DELETE FROM processing_job WHERE ip_record_id IN :ids"),
            {"ids": tuple(QA_RECORD_IDS)}
        ).rowcount
        print(f"   Deleted {del_jobs} rows from processing_job")

        # G. FieldProvenance
        del_prov = session.execute(
            text("DELETE FROM field_provenance WHERE ip_record_id IN :ids OR (master_ip_id IS NOT NULL AND master_ip_id IN :mids)"),
            {"ids": tuple(QA_RECORD_IDS), "mids": tuple(qa_master_ids) if qa_master_ids else ("none",)}
        ).rowcount
        print(f"   Deleted {del_prov} rows from field_provenance")

        # H. IpContributor
        del_contrib = session.execute(
            text("DELETE FROM ip_contributor WHERE ip_record_id IN :ids"),
            {"ids": tuple(QA_RECORD_IDS)}
        ).rowcount
        print(f"   Deleted {del_contrib} rows from ip_contributor")

        # I. IpFile
        del_files = session.execute(
            text("DELETE FROM ip_file WHERE ip_record_id IN :ids OR (master_ip_id IS NOT NULL AND master_ip_id IN :mids)"),
            {"ids": tuple(QA_RECORD_IDS), "mids": tuple(qa_master_ids) if qa_master_ids else ("none",)}
        ).rowcount
        print(f"   Deleted {del_files} rows from ip_file")

        # J. IpRecord
        del_recs = session.execute(
            text("DELETE FROM ip_record WHERE id IN :ids"),
            {"ids": tuple(QA_RECORD_IDS)}
        ).rowcount
        print(f"   Deleted {del_recs} rows from ip_record")

        # K. Master IP dependent rows & MasterIpRecord
        if qa_master_ids:
            del_mcontrib = session.execute(
                text("DELETE FROM master_ip_contributor WHERE master_ip_id IN :mids"),
                {"mids": tuple(qa_master_ids)}
            ).rowcount
            print(f"   Deleted {del_mcontrib} rows from master_ip_contributor")

            del_mverif = session.execute(
                text("DELETE FROM master_verification_attempt WHERE master_ip_id IN :mids"),
                {"mids": tuple(qa_master_ids)}
            ).rowcount
            print(f"   Deleted {del_mverif} rows from master_verification_attempt")

            del_msnap = session.execute(
                text("DELETE FROM faculty_profile_snapshot WHERE master_ip_id IN :mids"),
                {"mids": tuple(qa_master_ids)}
            ).rowcount
            print(f"   Deleted {del_msnap} rows from faculty_profile_snapshot")

            del_massoc = session.execute(
                text("DELETE FROM faculty_ip_association WHERE master_ip_id IN :mids"),
                {"mids": tuple(qa_master_ids)}
            ).rowcount
            print(f"   Deleted {del_massoc} rows from faculty_ip_association")

            del_master = session.execute(
                text("DELETE FROM master_ip_record WHERE id IN :mids"),
                {"mids": tuple(qa_master_ids)}
            ).rowcount
            print(f"   Deleted {del_master} rows from master_ip_record")

        # Commit transaction
        session.commit()
        print("\n>>> DATABASE TRANSACTION COMMITTED SUCCESSFULLY <<<")

        # =========================================================================
        # POST-CLEANUP VERIFICATION
        # =========================================================================
        print("\n3. Post-cleanup Database Verification:")
        final_count = session.execute(text("SELECT count(*) FROM ip_record")).scalar()
        print(f"   Final total records in ip_record: {final_count}")
        assert final_count == 16, f"ERROR: Expected exactly 16 records, found {final_count}"

        final_files = session.execute(text("SELECT count(*) FROM ip_file")).scalar()
        print(f"   Final total files in ip_file: {final_files}")
        assert final_files == 16, f"ERROR: Expected exactly 16 files, found {final_files}"

        # Verify all 16 baseline records remain
        remaining_baseline = session.execute(
            text("SELECT id FROM ip_record WHERE id IN :ids"),
            {"ids": tuple(BASELINE_RECORD_IDS)}
        ).fetchall()
        print(f"   Remaining baseline records verified: {len(remaining_baseline)} / 16")
        assert len(remaining_baseline) == 16, "ERROR: Some baseline records are missing!"

        # Verify QA records are gone
        remaining_qa = session.execute(
            text("SELECT id FROM ip_record WHERE id IN :ids"),
            {"ids": tuple(QA_RECORD_IDS)}
        ).fetchall()
        print(f"   Remaining QA records: {len(remaining_qa)} (Expected: 0)")
        assert len(remaining_qa) == 0, "ERROR: QA records still exist in database!"

        # Verify orphaned files
        orphaned = session.execute(
            text("SELECT count(*) FROM ip_file f LEFT JOIN ip_record r ON f.ip_record_id = r.id WHERE f.ip_record_id IS NOT NULL AND r.id IS NULL")
        ).scalar()
        print(f"   Orphaned ip_file rows: {orphaned} (Expected: 0)")
        assert orphaned == 0, "ERROR: Orphaned files detected!"

        print("\nCLEANUP SUCCEEDED AND ALL POST-CLEANUP ASSERTIONS PASSED.")
        return True

    except Exception as e:
        session.rollback()
        print(f"CLEANUP FAILED with exception: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        session.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Perform actual deletion")
    args = parser.parse_args()
    success = run_cleanup(execute=args.execute)
    sys.exit(0 if success else 1)
