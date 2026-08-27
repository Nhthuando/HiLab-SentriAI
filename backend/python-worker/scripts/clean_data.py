import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.connection import init_db_pool, close_db_pool, get_db_pool


async def main():
    print("Connecting to Neon PostgreSQL database...")
    await init_db_pool()
    pool = get_db_pool()

    async with pool.acquire() as conn:
        print("Cleaning up old gate_events...")
        events_deleted = await conn.execute("DELETE FROM gate_events")
        print(f"-> {events_deleted}")

        print("Cleaning up old registered_vehicles...")
        vehicles_deleted = await conn.execute("DELETE FROM registered_vehicles")
        print(f"-> {vehicles_deleted}")

    await close_db_pool()
    print("[OK] Successfully cleaned database tables for fresh testing!")


if __name__ == "__main__":
    asyncio.run(main())
