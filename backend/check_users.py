import psycopg2
conn = psycopg2.connect('postgresql://postgres@localhost:5432/faculty_portal')
cur = conn.cursor()
cur.execute('SELECT id, email, full_name, role, faculty_id, is_active, password_hash FROM "user"')
rows = cur.fetchall()
for row in rows:
    print(row)
cur.close()
conn.close()