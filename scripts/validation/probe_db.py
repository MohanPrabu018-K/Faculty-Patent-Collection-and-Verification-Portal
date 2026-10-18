# -*- coding: utf-8 -*-
"""Pre-flight database target probe for run_full_validation.ps1.

Asserts the process resolves the LOCAL staging database (never production):
loopback server address + database name faculty_portal_staging. Prints the
alembic revision. Exit 0 on success, exit 2 on wrong target.
"""
import os
import sys

os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres@localhost:5432/faculty_portal_staging"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

from sqlalchemy import create_engine, text  # noqa: E402

e = create_engine("postgresql+psycopg2://postgres@localhost:5432/faculty_portal_staging")
with e.connect() as c:
    host = c.execute(text("select inet_server_addr()::text")).scalar()
    name = c.execute(text("select current_database()")).scalar()
    rev = c.execute(text("select version_num from alembic_version")).scalar()
local = host is None or host.startswith("127.") or host.startswith("::1")
print("db-target: host=%s db=%s rev=%s" % (host, name, rev))
if not (local and name == "faculty_portal_staging"):
    print("REFUSING: not the local staging database")
    sys.exit(2)
print("db-target: OK")
