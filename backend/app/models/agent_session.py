"""Agent session persistence (MongoDB)."""
from datetime import datetime, timezone
from typing import List, Optional

from bson import ObjectId

from app.db import get_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_oid(val: Optional[str]) -> Optional[ObjectId]:
    """Safely convert to ObjectId, return None for invalid/empty/'null'/'undefined'."""
    if not val or val in ("null", "undefined", "NaN", "None"):
        return None
    try:
        return ObjectId(str(val).strip())
    except Exception:
        return None


def _oid_or_original(val: Optional[str]):
    """Return ObjectId if valid, else original string, else None for empty."""
    if not val or val in ("null", "undefined", "NaN", "None", ""):
        return None
    oid = _safe_oid(val)
    return oid if oid is not None else val


async def create_agent_session(user_id: str, title: str, mode: str, project_id: Optional[str] = None) -> dict:
    now = _now()
    uid = _safe_oid(user_id)
    if uid is None:
        raise ValueError(f"Invalid user_id: {user_id}")
    doc = {
        "userId": uid,
        "title": title[:80],
        "mode": mode if mode in ("plan", "build") else "build",
        "status": "active",
        "createdAt": now,
        "updatedAt": now,
        "messages": [],
        "toolEvents": [],
        "changedFiles": [],
    }
    pid = _oid_or_original(project_id)
    if pid is not None:
        doc["projectId"] = pid
    result = await get_db().agent_sessions.insert_one(doc)
    return {**doc, "id": str(result.inserted_id)}


async def get_agent_session(user_id: str, session_id: str) -> Optional[dict]:
    uid = _safe_oid(user_id)
    sid = _safe_oid(session_id)
    if uid is None or sid is None:
        return None
    try:
        doc = await get_db().agent_sessions.find_one({"_id": sid, "userId": uid})
    except Exception:
        return None
    if doc is None:
        return None
    doc["id"] = str(doc["_id"])
    return doc


async def list_agent_sessions(user_id: str, limit: int = 50, project_id: Optional[str] = None) -> List[dict]:
    uid = _safe_oid(user_id)
    if uid is None:
        return []
    q: dict = {"userId": uid}
    pid = _oid_or_original(project_id)
    if pid is not None:
        q["projectId"] = pid
    try:
        cursor = get_db().agent_sessions.find(q).sort("updatedAt", -1).limit(limit)
        out = []
        async for doc in cursor:
            pid_val = doc.get("projectId")
            out.append(
                {
                    "id": str(doc["_id"]),
                    "title": doc.get("title", "Agent Session"),
                    "mode": doc.get("mode", "build"),
                    "status": doc.get("status", "active"),
                    "createdAt": doc.get("createdAt", ""),
                    "updatedAt": doc.get("updatedAt", ""),
                    "messageCount": len(doc.get("messages", [])),
                    "projectId": str(pid_val) if pid_val else None,
                }
            )
        return out
    except Exception as e:
        import logging
        logging.getLogger("uvicorn.error").error(f"list_agent_sessions failed: {e}", exc_info=True)
        return []


async def delete_agent_session(user_id: str, session_id: str) -> bool:
    sid = _safe_oid(session_id)
    uid = _safe_oid(user_id)
    if sid is None or uid is None:
        return False
    try:
        res = await get_db().agent_sessions.delete_one({"_id": sid, "userId": uid})
        return res.deleted_count > 0
    except Exception:
        return False


async def append_agent_message(user_id: str, session_id: str, role: str, content: str):
    uid = _safe_oid(user_id)
    sid = _safe_oid(session_id)
    if uid is None or sid is None:
        return
    try:
        await get_db().agent_sessions.update_one(
            {"_id": sid, "userId": uid},
            {"$push": {"messages": {"role": role, "content": content, "at": _now()}}, "$set": {"updatedAt": _now()}},
        )
    except Exception:
        pass


async def append_tool_event(user_id: str, session_id: str, event: dict):
    uid = _safe_oid(user_id)
    sid = _safe_oid(session_id)
    if uid is None or sid is None:
        return
    try:
        await get_db().agent_sessions.update_one(
            {"_id": sid, "userId": uid},
            {"$push": {"toolEvents": event}, "$set": {"updatedAt": _now()}},
        )
    except Exception:
        pass


async def mark_changed_files(user_id: str, session_id: str, files: List[str]):
    uid = _safe_oid(user_id)
    sid = _safe_oid(session_id)
    if uid is None or sid is None:
        return
    try:
        await get_db().agent_sessions.update_one(
            {"_id": sid, "userId": uid},
            {"$addToSet": {"changedFiles": {"$each": files}}, "$set": {"updatedAt": _now()}},
        )
    except Exception:
        pass


async def update_agent_status(user_id: str, session_id: str, status: str):
    uid = _safe_oid(user_id)
    sid = _safe_oid(session_id)
    if uid is None or sid is None:
        return
    try:
        await get_db().agent_sessions.update_one(
            {"_id": sid, "userId": uid},
            {"$set": {"status": status, "updatedAt": _now()}},
        )
    except Exception:
        pass


async def update_agent_title(user_id: str, session_id: str, title: str):
    uid = _safe_oid(user_id)
    sid = _safe_oid(session_id)
    if uid is None or sid is None:
        return
    try:
        await get_db().agent_sessions.update_one(
            {"_id": sid, "userId": uid},
            {"$set": {"title": title[:60], "updatedAt": _now()}},
        )
    except Exception:
        pass
