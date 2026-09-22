import asyncio
from app.core.database import engine
from sqlalchemy import text

async def q():
    async with engine.connect() as c:
        r = await c.execute(text("SELECT id, email, faculty_id, role, department_id, full_name FROM \"user\" WHERE email = :e"), {"e": "nagasai.boppana@faculty.edu"})
        row = r.fetchone()
        if row:
            print(f"Nagasai: id={row[0]}, email={row[1]}, faculty_id={row[2]}, role={row[3]}, dept={row[4]}, name={row[5]}")
        else:
            print("Nagasai not found")

        r2 = await c.execute(text("SELECT id, email, faculty_id, role, department_id FROM \"user\" WHERE email = :e"), {"e": "mv-hod@faculty.edu"})
        row2 = r2.fetchone()
        if row2:
            print(f"HOD: id={row2[0]}, email={row2[1]}, faculty_id={row2[2]}, role={row2[3]}, dept={row2[4]}")

        # Also check the HOD documents API - what dept does it use?
        r3 = await c.execute(text("SELECT department_id FROM \"user\" WHERE faculty_id = :fid"), {"fid": "FAC001"})
        row3 = r3.fetchone()
        if row3:
            print(f"FAC001 dept: {row3[0]}")

asyncio.run(q())
