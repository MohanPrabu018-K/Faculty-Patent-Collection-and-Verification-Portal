import psycopg2
conn = psycopg2.connect('postgresql://postgres@localhost:5432/faculty_portal')
conn.autocommit = True
cur = conn.cursor()
cur.execute('ALTER TYPE processing_status_enum ADD VALUE IF NOT EXISTS \'COMPLETED_WITH_ERRORS\'')
print('Enum updated')
cur.close()
conn.close()