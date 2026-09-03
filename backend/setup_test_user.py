import psycopg2
from app.core.security import hash_password

# Use a known password
password = "testpassword123"
password_hash = hash_password(password)
print(f"Password: {password}")
print(f"Hash: {password_hash}")

conn = psycopg2.connect('postgresql://postgres@localhost:5432/faculty_portal')
cur = conn.cursor()

# Update existing test user
cur.execute('''
    UPDATE "user" 
    SET password_hash = %s, is_active = true
    WHERE email = %s
''', (password_hash, 'test@faculty.edu'))

conn.commit()
print(f"Rows updated: {cur.rowcount}")

# Verify
cur.execute('SELECT id, email, password_hash FROM "user" WHERE email = %s', ('test@faculty.edu',))
row = cur.fetchone()
print(f"Updated user: {row}")

cur.close()
conn.close()