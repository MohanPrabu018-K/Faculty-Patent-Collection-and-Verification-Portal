import sys
sys.path.insert(0, r'E:\Faculty profile portal\backend')
from sqlalchemy import create_engine, text

engine = create_engine('postgresql+asyncpg://faculty_user:change-me@localhost:5432/faculty_portal')
with engine.connect() as conn:
    result = conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name"))
    tables = result.fetchall()
    print('Tables created:')
    for t in tables:
        print(f'  - {t[0]}')