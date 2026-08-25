"""CLI script to reset operational and evaluation databases to clean initial demo state."""

import asyncio
import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from httpx import ASGITransport, AsyncClient

from retrypay.api.app import app
from retrypay.config import get_settings
from retrypay.storage.database import get_engine, init_db


async def async_main() -> None:
    settings = get_settings()
    engine = get_engine(settings.DATABASE_URL)
    await init_db(engine)

    print("Resetting ReTryPay demo database...")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/simulator/reset")
        if resp.status_code == 200:
            print("Successfully reset demo database.")
            print(resp.json())
        else:
            print(f"Failed to reset: {resp.status_code} {resp.text}")


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
