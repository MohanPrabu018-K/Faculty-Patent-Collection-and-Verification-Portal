#!/usr/bin/env python3
import asyncio
import asyncpg

async def main():
    try:
        conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5432/postgres')
        print("Connected to local postgres!")
        dbs = await conn.fetch("SELECT datname FROM pg_database WHERE datname = 'test_fpp'")
        if not dbs:
            await conn.execute("CREATE DATABASE test_fpp")
            print("Created database 'test_fpp'")
        else:
            print("Database 'test_fpp' already exists.")
        await conn.close()
    except Exception as e:
        print("Local postgres error:", e)

if __name__ == "__main__":
    asyncio.run(main())
