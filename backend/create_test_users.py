"""Idempotently create the test users required by the Playwright suite.

Creates/updates:
  - Faculty A: test@faculty.edu       / TestPass123!  (FAC001)
  - Faculty B: faculty2@faculty.edu   / TestPass456!  (FAC002)
  - Admin:     admin@faculty.edu      / AdminPass123! (super_admin)
"""
import os

import psycopg2
from app.core.security import hash_password

USERS = [
    ("test-faculty-001", "test@faculty.edu", "Test Faculty", "faculty", "FAC001", "TestPass123!"),
    ("test-faculty-002", "faculty2@faculty.edu", "Faculty Two", "faculty", "FAC002", "TestPass456!"),
    ("test-admin-001", "admin@faculty.edu", "Admin User", "super_admin", None, "AdminPass123!"),
]

# Target the same database the application is configured for (DATABASE_URL in the
# backend .env - now Neon). Falls back to a local postgres if config import fails.
try:
    from app.core.database import _sync_url, _sync_connect_args

    _dsn = _sync_url.replace("postgresql+psycopg2://", "postgresql://")
    _connect_kwargs = dict(_sync_connect_args)
except Exception:
    _dsn = os.getenv("DATABASE_URL_SYNC", "postgresql://postgres@localhost:5432/faculty_portal")
    _connect_kwargs = {}

conn = psycopg2.connect(_dsn, **_connect_kwargs)
conn.autocommit = True
cur = conn.cursor()

for user_id, email, full_name, role, faculty_id, password in USERS:
    password_hash = hash_password(password)
    cur.execute(
        """
        INSERT INTO "user" (id, email, password_hash, full_name, role, faculty_id, is_active, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, TRUE, NOW(), NOW())
        ON CONFLICT (id) DO UPDATE SET
            email = EXCLUDED.email,
            password_hash = EXCLUDED.password_hash,
            full_name = EXCLUDED.full_name,
            role = EXCLUDED.role,
            faculty_id = EXCLUDED.faculty_id,
            is_active = TRUE,
            updated_at = NOW()
        """,
        (user_id, email, password_hash, full_name, role, faculty_id),
    )
    print(f"Upserted {email} ({role}, faculty_id={faculty_id})")

cur.close()
conn.close()
print("Done.")
