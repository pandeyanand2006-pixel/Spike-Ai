"""Bridge device and pairing persistence."""
from datetime import datetime, timezone, timedelta
from typing import Optional, List
import secrets

from bson import ObjectId

from app.db import get_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expiry(minutes: int = 10) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


async def create_pairing_code(user_id: str) -> dict:
    """Generate a short pairing code for the user."""
    from app.models.project import _safe_oid
    uid = _safe_oid(user_id)
    if uid is None:
        raise ValueError("Invalid user_id")
    code = f"{secrets.randbelow(9000)+1000:04d}-{secrets.randbelow(9000)+1000:04d}"
    # e.g., 1234-5678
    doc = {
        "userId": uid,
        "code": code,
        "createdAt": _now(),
        "expiresAt": _expiry(10),
        "used": False,
    }
    await get_db().bridge_pairings.insert_one(doc)
    return {"code": code, "expiresAt": doc["expiresAt"]}


async def verify_pairing_code(code: str, user_id: Optional[str] = None) -> Optional[dict]:
    """Verify a pairing code, mark as used, return pairing doc.

    When user_id is given, the code must belong to that user — codes
    are single-user secrets, never cross-user.
    """
    try:
        q: dict = {"code": code.strip().upper(), "used": False}
        if user_id is not None:
            from app.models.project import _safe_oid
            uid = _safe_oid(user_id)
            if uid is None:
                return None
            q["userId"] = uid
        doc = await get_db().bridge_pairings.find_one(q)
    except Exception:
        return None
    if not doc:
        return None
    # Check expiry
    try:
        exp = datetime.fromisoformat(doc["expiresAt"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > exp:
            return None
    except Exception:
        pass
    await get_db().bridge_pairings.update_one({"_id": doc["_id"]}, {"$set": {"used": True}})
    return doc


async def create_device(user_id: str, name: str = "Windows PC") -> dict:
    """Create a bridge device for the user."""
    from app.models.project import _safe_oid
    uid = _safe_oid(user_id)
    if uid is None:
        raise ValueError("Invalid user_id")
    token = secrets.token_urlsafe(32)
    doc = {
        "userId": uid,
        "name": name,
        "token": token,
        "createdAt": _now(),
        "lastSeen": _now(),
        "status": "online",
    }
    res = await get_db().bridge_devices.insert_one(doc)
    doc["id"] = str(res.inserted_id)
    return doc


async def get_device_by_token(token: str) -> Optional[dict]:
    try:
        doc = await get_db().bridge_devices.find_one({"token": token})
    except Exception:
        return None
    if not doc:
        return None
    doc["id"] = str(doc["_id"])
    return doc


async def touch_device(device_id: str):
    try:
        from app.models.project import _safe_oid
        oid = _safe_oid(device_id)
        if oid is None:
            return
        await get_db().bridge_devices.update_one({"_id": oid}, {"$set": {"lastSeen": _now(), "status": "online"}})
    except Exception:
        pass


async def list_devices(user_id: str) -> List[dict]:
    from app.models.project import _safe_oid
    uid = _safe_oid(user_id)
    if uid is None:
        return []
    try:
        cursor = get_db().bridge_devices.find({"userId": uid}).sort("lastSeen", -1)
        out = []
        async for doc in cursor:
            doc["id"] = str(doc["_id"])
            out.append(doc)
        return out
    except Exception:
        return []


async def delete_device(user_id: str, device_id: str) -> bool:
    from app.models.project import _safe_oid
    uid = _safe_oid(user_id)
    did = _safe_oid(device_id)
    if uid is None or did is None:
        return False
    try:
        res = await get_db().bridge_devices.delete_one({"_id": did, "userId": uid})
        return res.deleted_count > 0
    except Exception:
        return False
