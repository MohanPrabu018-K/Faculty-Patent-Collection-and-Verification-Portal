# -*- coding: utf-8 -*-
"""Staging-fixture presence probe for run_full_validation.ps1 (Phase 7 gate).
Prints 1 when the stg.* fixture accounts exist, else 0. Read-only."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

from sqlalchemy import create_engine, text  # noqa: E402

e = create_engine("postgresql+psycopg2://postgres@localhost:5432/faculty_portal_staging")
with e.connect() as c:
    n = c.execute(text("select count(*) from \"user\" where email='stg.faculty01@staging.example.com'")).scalar()
print(1 if n == 1 else 0)
