"""Delete ONLY the rows created by ``provision_staging.py`` (prefix ``stg-``).

Safety
------
* Guards ``STAGING_DATABASE_URL`` with the same fail-closed rules as
  provisioning (production hosts are never deletable).
* Every DELETE is scoped by an ``stg-`` id prefix, so pre-existing / real rows
  are structurally impossible to touch.
* Dry-run by default: pass ``--yes`` to actually delete.

Usage
-----
    $env:STAGING_DATABASE_URL = 'postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/faculty_portal_staging'
    python scripts/staging/teardown_staging.py          # report only
    python scripts/staging/teardown_staging.py --yes    # delete
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent
_BACKEND_DIR = _REPO_ROOT / "backend"
sys.path.insert(0, str(_THIS_DIR))
sys.path.insert(0, str(_BACKEND_DIR))

import guard  # noqa: E402

STG = "stg-%"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Remove staging rows (id prefix stg-).")
    parser.add_argument("--yes", action="store_true", help="actually delete (default is dry-run)")
    args = parser.parse_args(argv)

    url = guard.resolve_staging_database_url()
    os.environ["DATABASE_URL"] = url
    os.environ.setdefault("APP_ENV", "development")

    from sqlalchemy import delete, func, or_, select  # noqa: E402
    from app.core.database import sync_session_factory  # noqa: E402
    from app.models.base import (  # noqa: E402
        AssociationRequest,
        AuditLog,
        ConflictCase,
        Department,
        Designation,
        DuplicateCase,
        FacultyIpAssociation,
        FieldProvenance,
        IdentityConflict,
        IpContributor,
        IpFile,
        IpRecord,
        Notification,
        ProcessingJob,
        User,
        VerificationAttempt,
    )

    session = sync_session_factory()

    # Each entry: (label, model, OR-list of stg- scoped conditions).
    plan = [
        ("notifications", Notification, [
            Notification.id.like(STG),
            Notification.related_entity_id.like(STG),
            Notification.user_id.like(STG),
        ]),
        ("verification_attempts", VerificationAttempt, [
            VerificationAttempt.id.like(STG),
            VerificationAttempt.ip_record_id.like(STG),
        ]),
        ("processing_jobs", ProcessingJob, [
            ProcessingJob.id.like(STG),
            ProcessingJob.ip_record_id.like(STG),
        ]),
        ("ip_files", IpFile, [IpFile.id.like(STG), IpFile.ip_record_id.like(STG), IpFile.uploaded_by.like(STG)]),
        ("field_provenance", FieldProvenance, [
            FieldProvenance.id.like(STG),
            FieldProvenance.ip_record_id.like(STG),
        ]),
        ("association_requests", AssociationRequest, [
            AssociationRequest.id.like(STG),
            AssociationRequest.ip_record_id.like(STG),
            AssociationRequest.requesting_faculty_id.like(STG),
            AssociationRequest.target_faculty_id.like(STG),
            AssociationRequest.requester_id.like(STG),
            AssociationRequest.recipient_id.like(STG),
        ]),
        ("identity_conflicts", IdentityConflict, [
            IdentityConflict.id.like(STG),
            IdentityConflict.user_id_1.like(STG),
            IdentityConflict.user_id_2.like(STG),
        ]),
        ("duplicate_cases", DuplicateCase, [
            DuplicateCase.id.like(STG),
            DuplicateCase.ip_record_id_1.like(STG),
            DuplicateCase.ip_record_id_2.like(STG),
        ]),
        ("conflict_cases", ConflictCase, [
            ConflictCase.id.like(STG),
            ConflictCase.ip_record_id.like(STG),
        ]),
        ("faculty_ip_associations", FacultyIpAssociation, [
            FacultyIpAssociation.id.like(STG),
            FacultyIpAssociation.faculty_id.like(STG),
            FacultyIpAssociation.master_ip_id.like(STG),
        ]),
        ("ip_contributors", IpContributor, [
            IpContributor.id.like(STG),
            IpContributor.ip_record_id.like(STG),
            IpContributor.user_id.like(STG),
        ]),
        ("ip_records", IpRecord, [IpRecord.id.like(STG), IpRecord.uploader_id.like(STG)]),
        ("audit_logs", AuditLog, [
            AuditLog.id.like(STG),
            AuditLog.actor_id.like(STG),
            AuditLog.entity_id.like(STG),
        ]),
        ("users", User, [User.id.like(STG), User.email.like("stg.%@staging.example.com")]),
        ("designations", Designation, [Designation.id.like(STG)]),
        ("departments", Department, [Department.id.like(STG)]),
    ]

    mode = "DELETE" if args.yes else "DRY-RUN"
    print(f"[teardown] {mode} against {guard.host_of(url)}/{guard.db_name_of(url)}")
    try:
        for label, model, conditions in plan:
            cond = or_(*conditions)
            count = session.execute(select(func.count()).select_from(model).where(cond)).scalar_one()
            print(f"  {label}: {count}")
            if args.yes and count:
                session.execute(delete(model).where(cond))
        if args.yes:
            session.commit()
            print("[teardown] committed")
        else:
            print("[teardown] dry-run only; pass --yes to delete")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
