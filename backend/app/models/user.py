"""User document helpers."""
from datetime import datetime, timezone
from typing import Optional

from app.db import get_db


async def create_user(name: str, email: str, password_hash: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    user = {
        "name": name,
        "email": email.lower(),
        "password_hash": password_hash,
        "createdAt": now,
        "updatedAt": now,
    }
    result = await get_db().users.insert_one(user)
    return {**user, "id": str(result.inserted_id)}


async def find_by_email(email: str) -> Optional[dict]:
    doc = await get_db().users.find_one({"email": email.lower()})
    if doc is None:
        return None
    return {**doc, "id": str(doc["_id"])}


async def find_by_id(user_id: str) -> Optional[dict]:
    from bson import ObjectId

    try:
        doc = await get_db().users.find_one({"_id": ObjectId(user_id)})
    except Exception:
        return None
    if doc is None:
        return None
    return {**doc, "id": str(doc["_id"])}


async def update_password(user_id: str, password_hash: str) -> None:
    from bson import ObjectId

    await get_db().users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"password_hash": password_hash,
                  "updatedAt": datetime.now(timezone.utc).isoformat()}},
    )
