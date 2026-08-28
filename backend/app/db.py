"""MongoDB connection using Motor (async driver)."""
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import get_settings

_client: AsyncIOMotorClient | None = None


def get_db():
    """Return the application database client."""
    global _client
    settings = get_settings()
    if _client is None:
        _client = AsyncIOMotorClient(settings.mongodb_uri)
    return _client[settings.database_name]


async def ping() -> bool:
    """Return True if database is reachable."""
    try:
        await get_db().command("ping")
        return True
    except Exception:
        return False
