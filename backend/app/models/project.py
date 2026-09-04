"""Project persistence — MongoDB + filesystem workspace binding."""
from datetime import datetime, timezone
from typing import List, Optional

from bson import ObjectId

from app.db import get_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def create_project(user_id: str, name: str, description: str, template: str, workspace: str, stack: str) -> dict:
    now = _now()
    doc = {
        "userId": ObjectId(user_id),
        "name": name.strip()[:80],
        "description": (description or "")[:300],
        "template": template or "other",
        "workspace": workspace,
        "stack": stack or "",
        "status": "ready",
        "createdAt": now,
        "updatedAt": now,
        "lastOpenedAt": now,
    }
    res = await get_db().projects.insert_one(doc)
    doc["id"] = str(res.inserted_id)
    return doc


async def get_project(user_id: str, project_id: str) -> Optional[dict]:
    try:
        doc = await get_db().projects.find_one({"_id": ObjectId(project_id), "userId": ObjectId(user_id)})
    except Exception:
        return None
    if not doc:
        return None
    doc["id"] = str(doc["_id"])
    return doc


async def list_projects(user_id: str, search: str = "") -> List[dict]:
    q: dict = {"userId": ObjectId(user_id)}
    if search:
        q["name"] = {"$regex": search, "$options": "i"}
    cursor = get_db().projects.find(q).sort("lastOpenedAt", -1).limit(100)
    out = []
    async for doc in cursor:
        doc["id"] = str(doc["_id"])
        out.append(doc)
    return out


async def update_project(user_id: str, project_id: str, fields: dict) -> bool:
    fields["updatedAt"] = _now()
    try:
        res = await get_db().projects.update_one(
            {"_id": ObjectId(project_id), "userId": ObjectId(user_id)},
            {"$set": fields},
        )
        return res.modified_count > 0
    except Exception:
        return False


async def touch_project(user_id: str, project_id: str):
    try:
        await get_db().projects.update_one(
            {"_id": ObjectId(project_id), "userId": ObjectId(user_id)},
            {"$set": {"lastOpenedAt": _now(), "updatedAt": _now()}},
        )
    except Exception:
        pass


async def delete_project(user_id: str, project_id: str) -> bool:
    try:
        oid = ObjectId(project_id)
    except Exception:
        return False
    res = await get_db().projects.delete_one({"_id": oid, "userId": ObjectId(user_id)})
    # Also delete agent sessions for this project
    await get_db().agent_sessions.delete_many({"userId": ObjectId(user_id), "projectId": oid})
    return res.deleted_count > 0
