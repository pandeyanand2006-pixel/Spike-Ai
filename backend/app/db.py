"""MongoDB connection using Motor (async driver)."""
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import get_settings

_client: AsyncIOMotorClient | None = None


def get_db():
    """Return the application database client.

    Fail-fast timeouts are critical: without them a hanging MongoDB
    connection holds the request open until the Render proxy gives up
    and returns 502 to the browser (the /api/agent/sessions 502).
    """
    global _client
    settings = get_settings()
    if _client is None:
        _client = AsyncIOMotorClient(
            settings.mongodb_uri,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=10000,
        )
    return _client[settings.database_name]


async def ping() -> bool:
    """Return True if database is reachable."""
    try:
        await get_db().command("ping")
        return True
    except Exception:
        return False
