"""Reproducible, fail-closed provisioning of the staging test dataset.

What it does
------------
1. Reads the staging database URL from ``STAGING_DATABASE_URL`` (never the app
   ``DATABASE_URL``) and verifies it is disposable via ``guard.py``.
2. Upserts three staging departments + two designations.
3. Upserts the synthetic test accounts (10 faculty / 3 HOD / 1 Super Admin,
   plus one extra deactivated faculty account for the negative test).
4. Upserts deterministic scenario records (id prefix ``stg-rec-``) plus
   contributors, one duplicate case, one conflict case and two pending
   association requests, so the authenticated E2E/API scenarios have stable
   preconditions without exercising the heavy OCR pipeline.
5. Writes ``frontend/tests-staging/.staging-fixtures.json`` (gitignored) with
   resolved credentials + ids for the Playwright staging suite.

Safety
------
* Refuses any non-disposable DB (production deny-list wins, always).
* Never deletes or modifies pre-existing non-``stg-`` rows.
* Idempotent: re-running converges to the same state and does not duplicate
  rows or bump history.
* Does NOT run automatically anywhere; it is a manual, operator-invoked step.

Usage
-----
    $env:STAGING_DATABASE_URL = 'postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/faculty_portal_staging'
    python scripts/staging/provision_staging.py --create-database --migrate
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import string
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

# --- make guard importable + backend importable -------------------------------
_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent
_BACKEND_DIR = _REPO_ROOT / "backend"
sys.path.insert(0, str(_THIS_DIR))
sys.path.insert(0, str(_BACKEND_DIR))

import guard  # noqa: E402

FIXTURES_PATH = _REPO_ROOT / "frontend" / "tests-staging" / ".staging-fixtures.json"
RESOLVED_ACCOUNTS_PATH = _THIS_DIR / "staging_accounts.local.json"
EXAMPLE_ACCOUNTS_PATH = _THIS_DIR / "staging_accounts.example.json"

# Deterministic ids so teardown can find exactly what we created.
DEPT_IDS = {"A": "stg-dept-a", "B": "stg-dept-b", "C": "stg-dept-c"}
DESIG_PROF = "stg-desig-professor"
DESIG_HOD = "stg-desig-hod"

_PW_ALPHABET = string.ascii_letters + string.digits + "!@#%^*-_=+"


def _gen_password(length: int = 24) -> str:
    rng = secrets.SystemRandom()
    return "".join(rng.choice(_PW_ALPHABET) for _ in range(length))


def _load_accounts() -> dict:
    if RESOLVED_ACCOUNTS_PATH.exists():
        return json.loads(RESOLVED_ACCOUNTS_PATH.read_text(encoding="utf-8"))
    spec = json.loads(EXAMPLE_ACCOUNTS_PATH.read_text(encoding="utf-8"))
    for acc in spec["accounts"]:
        if not acc.get("password"):
            acc["password"] = _gen_password()
    RESOLVED_ACCOUNTS_PATH.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    return spec


def _user_id(key: str) -> str:
    return f"stg-user-{key}"


# --- optional DB creation / migration ----------------------------------------


def _create_database_if_missing(staging_url: str) -> None:
    import psycopg2
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(staging_url.replace("+asyncpg", "").replace("+psycopg2", ""))
    db_name = parts.path.lstrip("/")
    admin = urlunsplit((parts.scheme, parts.netloc, "/postgres", "", ""))
    conn = psycopg2.connect(admin)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
            if cur.fetchone():
                print(f"[provision] database {db_name!r} already exists")
            else:
                cur.execute(f'CREATE DATABASE "{db_name}"')
                print(f"[provision] created database {db_name!r}")
    finally:
        conn.close()


def _run_migrations(staging_url: str) -> None:
    env = dict(os.environ)
    env["DATABASE_URL"] = staging_url
    env.setdefault("APP_ENV", "development")
    print("[provision] running alembic upgrade head ...")
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(_REPO_ROOT / "alembic.ini"), "upgrade", "head"],
        check=True,
        cwd=str(_REPO_ROOT),
        env=env,
    )


# --- seeding ------------------------------------------------------------------


def _seed(staging_url: str, spec: dict) -> dict:
    # Point the app's own DB layer at the staging DB *before* importing it, so
    # the sync engine resolves the staging URL and never the production .env.
    os.environ["DATABASE_URL"] = staging_url
    os.environ.setdefault("APP_ENV", "development")

    from app.core.database import sync_session_factory  # noqa: E402
    from app.core.security import hash_password  # noqa: E402
    from app.models.base import (  # noqa: E402
        AssociationRequest,
        ConflictCase,
        Department,
        Designation,
        DuplicateCase,
        IpContributor,
        IpRecord,
        User,
    )

    session = sync_session_factory()
    accounts_by_key: dict[str, dict] = {}

    def upsert(model, row_id: str, **fields):
        row = session.get(model, row_id)
        if row is None:
            row = model(id=row_id, **fields)
            session.add(row)
        else:
            for key, value in fields.items():
                setattr(row, key, value)
        session.flush()
        return row

    try:
        # 1. departments + designations
        for key, dept in DEPT_IDS.items():
            upsert(Department, dept, name=spec["departments"][key], code=f"STG-{key}", status="active", is_active=True)
        upsert(Designation, DESIG_PROF, title="Staging Professor", name="Professor", level="faculty", status="active", is_active=True)
        upsert(Designation, DESIG_HOD, title="Staging HOD", name="HOD", level="hod", status="active", is_active=True)

        # 2. users
        for acc in spec["accounts"]:
            dept_key = acc.get("department")
            dept_id = DEPT_IDS.get(dept_key) if dept_key else None
            desig_id = DESIG_HOD if acc["role"] == "hod_admin" else (DESIG_PROF if dept_id else None)
            is_active = acc.get("is_active", True)
            upsert(
                User,
                _user_id(acc["key"]),
                email=acc["email"],
                official_email=acc["email"],
                password_hash=hash_password(acc["password"]),
                full_name=acc["full_name"],
                role=acc["role"],
                faculty_id=acc.get("faculty_id"),
                department_id=dept_id,
                designation_id=desig_id,
                status="active" if is_active else "inactive",
                is_active=is_active,
            )
            accounts_by_key[acc["key"]] = {
                "id": _user_id(acc["key"]),
                "email": acc["email"],
                "password": acc["password"],
                "role": acc["role"],
                "faculty_id": acc.get("faculty_id"),
                "department_id": dept_id,
                "is_active": is_active,
            }

        u = lambda key: _user_id(key)  # noqa: E731

        def make_record(rec_id, uploader_key, dept_key, **fields):
            dept_id = DEPT_IDS[dept_key]
            fields.setdefault("workflow_state", "FACULTY_ASSOCIATION_PENDING")
            fields.setdefault("verification_status", "UNVERIFIED")
            fields.setdefault("processing_status", "COMPLETED")
            fields.setdefault("document_type", "CERTIFICATE")
            fields.setdefault("historical_department_id", dept_id)
            fields.setdefault("historical_department_name", spec["departments"][dept_key])
            return upsert(
                IpRecord,
                rec_id,
                uploader_id=u(uploader_key),
                department_id=dept_id,
                **fields,
            )

        # 3. scenario records
        #  a1: uploader faculty01 (dept A), internal contributor faculty02, external contributor.
        make_record("stg-rec-a1", "faculty01", "A", ip_type="PATENT", patent_number="STG-PAT-0001", title="Staging Patent A1 (synthetic)")
        #  a2: uploader faculty01, internal contributor faculty03 (for duplicate pair)
        make_record("stg-rec-a2", "faculty01", "A", ip_type="DESIGN_REGISTRATION", design_number="STG-DES-0002", title="Staging Design A2 (synthetic)")
        #  b1 / b1b: dept B, used for HOD scoping + duplicate case 2
        make_record("stg-rec-b1", "faculty05", "B", ip_type="PATENT", patent_number="STG-PAT-0005", title="Staging Patent B1 (synthetic)")
        make_record("stg-rec-b1b", "faculty05", "B", ip_type="PATENT", patent_number="STG-PAT-0006", title="Staging Patent B1b (synthetic)")
        #  c1: dept C, conflict case
        make_record("stg-rec-c1", "faculty08", "C", ip_type="PATENT", patent_number="STG-PAT-0008", title="Staging Patent C1 (synthetic)")
        #  external-only record (no other internal faculty)
        make_record("stg-rec-ext-only", "faculty01", "A", ip_type="PATENT", patent_number="STG-PAT-EXTONLY", title="Staging Patent External-only (synthetic)")
        #  grantable record: no internal contributors -> grants cleanly
        make_record(
            "stg-rec-grantable", "faculty01", "A",
            ip_type="PATENT", patent_number="STG-PAT-GRANTABLE",
            title="Staging Patent Grantable (synthetic)",
            workflow_state="FACULTY_ASSOCIATION_COMPLETE", verification_status="VERIFIED",
        )
        #  not-eligible record: verification required
        make_record(
            "stg-rec-needverify", "faculty01", "A",
            ip_type="PATENT", patent_number="STG-PAT-NEEDVERIFY",
            title="Staging Patent Needs Verification (synthetic)",
            workflow_state="VERIFICATION_REQUIRED", verification_status="VERIFICATION_REQUIRED",
        )
        #  HOD-scoping records past the faculty stage
        make_record(
            "stg-rec-hod-a", "faculty01", "A",
            ip_type="PATENT", patent_number="STG-PAT-HODA",
            title="Staging Patent HOD-A (synthetic)",
            workflow_state="FACULTY_ASSOCIATION_COMPLETE", verification_status="VERIFIED",
        )
        make_record(
            "stg-rec-hod-b", "faculty05", "B",
            ip_type="PATENT", patent_number="STG-PAT-HODB",
            title="Staging Patent HOD-B (synthetic)",
            workflow_state="FACULTY_ASSOCIATION_COMPLETE", verification_status="VERIFIED",
        )

        # 4. contributors (deterministic ids for idempotency)
        # Before seeding, purge DYNAMIC children created by a previous run
        # (accept-created contributor links, send-all-created requests) so
        # re-provisioning yields a deterministic starting state. Only rows tied
        # to stg- records / not carrying a deterministic fixture id are removed.
        session.query(IpContributor).filter(
            IpContributor.ip_record_id.like("stg-rec-%"),
            ~IpContributor.id.like("stg-con-%"),
        ).delete(synchronize_session=False)
        session.query(AssociationRequest).filter(
            AssociationRequest.ip_record_id.like("stg-rec-%"),
            ~AssociationRequest.id.like("stg-assoc-%"),
        ).delete(synchronize_session=False)
        session.flush()

        def contrib(cid, rec_id, *, user_key=None, name, external, order):
            upsert(
                IpContributor,
                cid,
                ip_record_id=rec_id,
                user_id=u(user_key) if user_key else None,
                name=name,
                contributor_type="EXTERNAL" if external else "INTERNAL_FACULTY",
                is_external=external,
                contributor_order=order,
                match_status="CONFIRMED" if user_key else "VERIFICATION_REQUIRED",
                source="FACULTY_CONFIRMED" if user_key else "CERTIFICATE_OCR",
            )

        contrib("stg-con-a1-01", "stg-rec-a1", user_key="faculty01", name="Staging Faculty 01", external=False, order=0)
        contrib("stg-con-a1-02", "stg-rec-a1", user_key="faculty02", name="Staging Faculty 02", external=False, order=1)
        contrib("stg-con-a1-03", "stg-rec-a1", name="Dr. N. Devakirubai", external=True, order=2)
        contrib("stg-con-a2-01", "stg-rec-a2", user_key="faculty01", name="Staging Faculty 01", external=False, order=0)
        contrib("stg-con-a2-02", "stg-rec-a2", user_key="faculty03", name="Staging Faculty 03", external=False, order=1)
        contrib("stg-con-b1-01", "stg-rec-b1", user_key="faculty05", name="Staging Faculty 05", external=False, order=0)
        contrib("stg-con-b1-02", "stg-rec-b1", user_key="faculty06", name="Staging Faculty 06", external=False, order=1)
        contrib("stg-con-c1-01", "stg-rec-c1", user_key="faculty08", name="Staging Faculty 08", external=False, order=0)
        contrib("stg-con-c1-02", "stg-rec-c1", user_key="faculty09", name="Staging Faculty 09", external=False, order=1)
        contrib("stg-con-ext-01", "stg-rec-ext-only", user_key="faculty01", name="Staging Faculty 01", external=False, order=0)
        contrib("stg-con-ext-02", "stg-rec-ext-only", name="Dr. N. Devakirubai", external=True, order=1)

        # 5. pending association requests (recipient-only + IDOR + HOD-denial tests)
        upsert(
            AssociationRequest, "stg-assoc-pending-01",
            ip_record_id="stg-rec-a1", requesting_faculty_id=u("faculty01"), target_faculty_id=u("faculty04"),
            requester_id=u("faculty01"), recipient_id=u("faculty04"), status="PENDING",
            reason="staging fixture",
        )
        upsert(
            AssociationRequest, "stg-assoc-pending-02",
            ip_record_id="stg-rec-b1", requesting_faculty_id=u("faculty05"), target_faculty_id=u("faculty07"),
            requester_id=u("faculty05"), recipient_id=u("faculty07"), status="PENDING",
            reason="staging fixture",
        )

        # 6. duplicate + conflict cases
        upsert(
            DuplicateCase, "stg-dup-01",
            ip_record_id_1="stg-rec-a1", ip_record_id_2="stg-rec-a2",
            detection_method="identifier", confidence=0.91, status="OPEN",
        )
        upsert(
            DuplicateCase, "stg-dup-02",
            ip_record_id_1="stg-rec-b1", ip_record_id_2="stg-rec-b1b",
            detection_method="identifier", confidence=0.88, status="OPEN",
        )
        upsert(
            ConflictCase, "stg-conf-01",
            ip_record_id="stg-rec-c1", conflict_type="DATA_MISMATCH", field_name="patent_number",
            detected_value="STG-PAT-0008", expected_value="STG-PAT-0008-X", severity="HIGH",
            description="Staging synthetic conflict for rule-D/HOD read-only tests", status="OPEN",
        )

        session.commit()
    finally:
        session.close()

    return accounts_by_key


def _write_fixtures(accounts_by_key: dict[str, dict]) -> None:
    FIXTURES_PATH.parent.mkdir(parents=True, exist_ok=True)
    fixtures = {
        "generated_at": datetime.now(UTC).isoformat(),
        "identity_source": "SYNTHETIC_PLACEHOLDER (never real faculty IDs)",
        "departments": DEPT_IDS,
        "accounts": accounts_by_key,
        "records": {
            "a1": "stg-rec-a1",
            "a2": "stg-rec-a2",
            "b1": "stg-rec-b1",
            "b1b": "stg-rec-b1b",
            "c1": "stg-rec-c1",
            "extOnly": "stg-rec-ext-only",
            "grantable": "stg-rec-grantable",
            "needVerify": "stg-rec-needverify",
            "hodA": "stg-rec-hod-a",
            "hodB": "stg-rec-hod-b",
        },
        "associations": {
            "pendingRecipient": "stg-assoc-pending-01",
            "pendingHod": "stg-assoc-pending-02",
        },
        "duplicates": {"deptA": "stg-dup-01", "deptB": "stg-dup-02"},
        "conflicts": {"deptC": "stg-conf-01"},
    }
    FIXTURES_PATH.write_text(json.dumps(fixtures, indent=2), encoding="utf-8")
    print(f"[provision] wrote fixtures -> {FIXTURES_PATH}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Provision the disposable staging dataset.")
    parser.add_argument("--create-database", action="store_true", help="create the DB if it does not exist")
    parser.add_argument("--migrate", action="store_true", help="run alembic upgrade head against the staging DB")
    args = parser.parse_args(argv)

    url = guard.resolve_staging_database_url()
    print(f"[provision] target = {guard.host_of(url)}/{guard.db_name_of(url)}")

    if args.create_database:
        _create_database_if_missing(url)
    if args.migrate:
        _run_migrations(url)

    spec = _load_accounts()
    accounts = _seed(url, spec)
    _write_fixtures(accounts)
    print(f"[provision] provisioned {len(accounts)} accounts + scenario records (idempotent)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
