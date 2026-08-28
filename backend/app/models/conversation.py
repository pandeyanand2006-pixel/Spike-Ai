"""Conversation and message document helpers."""
from datetime import datetime, timezone
from typing import List, Optional

from bson import ObjectId

from app.db import get_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def create_conversation(user_id: str, title: str, model: str) -> dict:
    now = _now()
    doc = {
        "userId": ObjectId(user_id),
        "title": title,
        "model": model,
        "archived": False,
        "pinned": False,
        "createdAt": now,
        "updatedAt": now,
    }
    result = await get_db().conversations.insert_one(doc)
    return {**doc, "id": str(result.inserted_id), "messages": []}


async def list_conversations(user_id: str, limit: int = 100) -> List[dict]:
    cursor = get_db().conversations.find(
        {"userId": ObjectId(user_id), "archived": False}
    ).sort("updatedAt", -1).limit(limit)
    out = []
    async for doc in cursor:
        count = await get_db().messages.count_documents(
            {"conversationId": doc["_id"]}
        )
        out.append({
            "id": str(doc["_id"]),
            "title": doc.get("title", "New Chat"),
            "updatedAt": doc.get("updatedAt", ""),
            "model": doc.get("model"),
            "messageCount": count,
        })
    return out


async def get_conversation(user_id: str, conversation_id: str) -> Optional[dict]:
    try:
        doc = await get_db().conversations.find_one(
            {"_id": ObjectId(conversation_id), "userId": ObjectId(user_id)}
        )
    except Exception:
        return None
    if doc is None:
        return None
    msgs = []
    cursor = get_db().messages.find(
        {"conversationId": doc["_id"]}
    ).sort("createdAt", 1)
    async for m in cursor:
        msgs.append({
            "id": str(m["_id"]),
            "role": m.get("role"),
            "content": m.get("content", ""),
            "createdAt": m.get("createdAt", ""),
        })
    return {
        "id": str(doc["_id"]),
        "title": doc.get("title", "New Chat"),
        "createdAt": doc.get("createdAt", ""),
        "updatedAt": doc.get("updatedAt", ""),
        "model": doc.get("model"),
        "messages": msgs,
    }


async def rename_conversation(user_id: str, conversation_id: str, title: str) -> bool:
    try:
        res = await get_db().conversations.update_one(
            {"_id": ObjectId(conversation_id), "userId": ObjectId(user_id)},
            {"$set": {"title": title, "updatedAt": _now()}},
        )
        return res.modified_count > 0
    except Exception:
        return False


async def delete_conversation(user_id: str, conversation_id: str) -> bool:
    try:
        oid = ObjectId(conversation_id)
    except Exception:
        return False
    res = await get_db().conversations.delete_one(
        {"_id": oid, "userId": ObjectId(user_id)}
    )
    await get_db().messages.delete_many({"conversationId": oid})
    return res.deleted_count > 0


async def add_message(user_id: str, conversation_id: str, role: str, content: str) -> str:
    oid = ObjectId(conversation_id)
    now = _now()
    msg = {
        "conversationId": oid,
        "userId": ObjectId(user_id),
        "role": role,
        "content": content,
        "createdAt": now,
    }
    result = await get_db().messages.insert_one(msg)
    await get_db().conversations.update_one(
        {"_id": oid, "userId": ObjectId(user_id)},
        {"$set": {"updatedAt": now}},
    )
    return str(result.inserted_id)
