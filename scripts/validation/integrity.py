# -*- coding: utf-8 -*-
"""Read-only staging integrity probe for run_full_validation.ps1 (Phase 11).
Prints key/value lines; exit 1 if any hard invariant fails."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

from sqlalchemy import create_engine, text  # noqa: E402

e = create_engine("postgresql+psycopg2://postgres@localhost:5432/faculty_portal_staging")
fails = []
with e.connect() as c:
    q = lambda s: c.execute(text(s)).scalar()  # noqa: E731
    assert q("select current_database()") == "faculty_portal_staging"
    rows = {
        "alembic": q("select version_num from alembic_version"),
        "idx011": q("select count(*) from pg_indexes where indexname='uq_assoc_live_pair_per_record'"),
        "orphan_notif": q("select count(*) from notification n left join \"user\" u on u.id=n.user_id "
                          "where n.user_id is not null and u.id is null"),
        "dup_pairs": q("select count(*) from (select ip_record_id, "
                       "coalesce(requesting_faculty_id,requester_id), "
                       "coalesce(target_faculty_id,recipient_id) from association_request "
                       "where status in ('PENDING','ACCEPTED') group by 1,2,3 having count(*)>1) t"),
        "hod_viol": q("select count(*) from (select department_id,count(*) from \"user\" "
                      "where role='hod_admin' and is_active=true and department_id is not null "
                      "group by 1 having count(*)>1) t"),
        "grant_date": q("select data_type from information_schema.columns "
                        "where table_name='ip_record' and column_name='grant_date'"),
    }
    for k, v in rows.items():
        print("%s: %s" % (k, v))
    if rows["orphan_notif"] != 0:
        fails.append("orphan notifications")
    if rows["dup_pairs"] != 0:
        fails.append("duplicate live pairs")
    if rows["hod_viol"] != 0:
        fails.append("HOD uniqueness violations")
    if rows["grant_date"] != "date":
        fails.append("grant_date not DATE")
if fails:
    print("INTEGRITY FAILURES: %s" % fails)
    sys.exit(1)
print("integrity: OK")
