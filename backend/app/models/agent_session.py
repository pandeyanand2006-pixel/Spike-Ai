"""Agent session persistence (MongoDB)."""
from datetime import datetime, timezone
from typing import List, Optional

from bson import ObjectId

from app.db import get_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def create_agent_session(user_id: str, title: str, mode: str) -> dict:
    now = _now()
    doc = {
        "userId": ObjectId(user_id),
        "title": title[:80],
        "mode": mode if mode in ("plan", "build") else "build",
        "status": "active",
        "createdAt": now,
        "updatedAt": now,
        "messages": [],
        "toolEvents": [],
        "changedFiles": [],
    }
    result = await get_db().agent_sessions.insert_one(doc)
    return {**doc, "id": str(result.inserted_id)}


async def get_agent_session(user_id: str, session_id: str) -> Optional[dict]:
    try:
        doc = await get_db().agent_sessions.find_one(
            {"_id": ObjectId(session_id), "userId": ObjectId(user_id)}
        )
    except Exception:
        return None
    if doc is None:
        return None
    doc["id"] = str(doc["_id"])
    return doc


async def list_agent_sessions(user_id: str, limit: int = 50) -> List[dict]:
    cursor = get_db().agent_sessions.find({"userId": ObjectId(user_id)}).sort("updatedAt", -1).limit(limit)
    out = []
    async for doc in cursor:
        out.append(
            {
                "id": str(doc["_id"]),
                "title": doc.get("title", "Agent Session"),
                "mode": doc.get("mode", "build"),
                "status": doc.get("status", "active"),
                "createdAt": doc.get("createdAt", ""),
                "updatedAt": doc.get("updatedAt", ""),
                "messageCount": len(doc.get("messages", [])),
            }
        )
    return out


async def delete_agent_session(user_id: str, session_id: str) -> bool:
    try:
        oid = ObjectId(session_id)
    except Exception:
        return False
    res = await get_db().agent_sessions.delete_one({"_id": oid, "userId": ObjectId(user_id)})
    return res.deleted_count > 0


async def append_agent_message(user_id: str, session_id: str, role: str, content: str):
    try:
        await get_db().agent_sessions.update_one(
            {"_id": ObjectId(session_id), "userId": ObjectId(user_id)},
            {"$push": {"messages": {"role": role, "content": content, "at": _now()}}, "$set": {"updatedAt": _now()}},
        )
    except Exception:
        pass


async def append_tool_event(user_id: str, session_id: str, event: dict):
    try:
        await get_db().agent_sessions.update_one(
            {"_id": ObjectId(session_id), "userId": ObjectId(user_id)},
            {"$push": {"toolEvents": event}, "$set": {"updatedAt": _now()}},
        )
    except Exception:
        pass


async def mark_changed_files(user_id: str, session_id: str, files: List[str]):
    try:
        await get_db().agent_sessions.update_one(
            {"_id": ObjectId(session_id), "userId": ObjectId(user_id)},
            {"$addToSet": {"changedFiles": {"$each": files}}, "$set": {"updatedAt": _now()}},
        )
    except Exception:
        pass


async def update_agent_status(user_id: str, session_id: str, status: str):
    try:
        await get_db().agent_sessions.update_one(
            {"_id": ObjectId(session_id), "userId": ObjectId(user_id)},
            {"$set": {"status": status, "updatedAt": _now()}},
        )
    except Exception:
        pass


async def update_agent_title(user_id: str, session_id: str, title: str):
    try:
        await get_db().agent_sessions.update_one(
            {"_id": ObjectId(session_id), "userId": ObjectId(user_id)},
            {"$set": {"title": title[:60], "updatedAt": _now()}},
        )
    except Exception:
        pass
