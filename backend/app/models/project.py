"""Project persistence — MongoDB + filesystem workspace binding."""
from datetime import datetime, timezone
from typing import List, Optional

from bson import ObjectId

from app.db import get_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_oid(val: Optional[str]) -> Optional[ObjectId]:
    if not val or val in ("null", "undefined", "NaN", "None"):
        return None
    try:
        return ObjectId(str(val).strip())
    except Exception:
        return None


async def create_project(user_id: str, name: str, description: str, template: str, workspace: str, stack: str) -> dict:
    uid = _safe_oid(user_id)
    if uid is None:
        raise ValueError(f"Invalid user_id: {user_id}")
    now = _now()
    doc = {
        "userId": uid,
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
    uid = _safe_oid(user_id)
    pid = _safe_oid(project_id)
    if uid is None or pid is None:
        return None
    try:
        doc = await get_db().projects.find_one({"_id": pid, "userId": uid})
    except Exception:
        return None
    if not doc:
        return None
    doc["id"] = str(doc["_id"])
    return doc


async def list_projects(user_id: str, search: str = "") -> List[dict]:
    uid = _safe_oid(user_id)
    if uid is None:
        return []
    q: dict = {"userId": uid}
    if search:
        q["name"] = {"$regex": search, "$options": "i"}
    try:
        cursor = get_db().projects.find(q).sort("lastOpenedAt", -1).limit(100)
        out = []
        async for doc in cursor:
            doc["id"] = str(doc["_id"])
            out.append(doc)
        return out
    except Exception as e:
        import logging
        logging.getLogger("uvicorn.error").error(f"list_projects failed: {e}", exc_info=True)
        return []


async def update_project(user_id: str, project_id: str, fields: dict) -> bool:
    uid = _safe_oid(user_id)
    pid = _safe_oid(project_id)
    if uid is None or pid is None:
        return False
    fields["updatedAt"] = _now()
    try:
        res = await get_db().projects.update_one(
            {"_id": pid, "userId": uid},
            {"$set": fields},
        )
        return res.modified_count > 0
    except Exception:
        return False


async def touch_project(user_id: str, project_id: str):
    uid = _safe_oid(user_id)
    pid = _safe_oid(project_id)
    if uid is None or pid is None:
        return
    try:
        await get_db().projects.update_one(
            {"_id": pid, "userId": uid},
            {"$set": {"lastOpenedAt": _now(), "updatedAt": _now()}},
        )
    except Exception:
        pass


async def delete_project(user_id: str, project_id: str) -> bool:
    pid = _safe_oid(project_id)
    uid = _safe_oid(user_id)
    if pid is None or uid is None:
        return False
    try:
        res = await get_db().projects.delete_one({"_id": pid, "userId": uid})
        await get_db().agent_sessions.delete_many({"userId": uid, "projectId": pid})
        return res.deleted_count > 0
    except Exception:
        return False
