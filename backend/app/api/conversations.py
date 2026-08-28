"""Conversation management endpoints."""
from fastapi import APIRouter, Depends, HTTPException, status

from app.middleware.auth import get_current_user
from app.models import conversation as conv
from app.schemas.conversation import (
    ConversationOut,
    ConversationSummary,
    ConversationUpdate,
)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationSummary])
async def list_conversations(user: dict = Depends(get_current_user)):
    items = await conv.list_conversations(user["id"])
    return [
        ConversationSummary(
            id=c["id"],
            title=c["title"],
            updatedAt=c["updatedAt"],
            model=c.get("model"),
        )
        for c in items
    ]


@router.get("/{conversation_id}", response_model=ConversationOut)
async def get_conversation(conversation_id: str, user: dict = Depends(get_current_user)):
    c = await conv.get_conversation(user["id"], conversation_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return ConversationOut(
        id=c["id"],
        title=c["title"],
        createdAt=c["createdAt"],
        updatedAt=c["updatedAt"],
        model=c.get("model"),
        messages=c["messages"],
    )


@router.patch("/{conversation_id}")
async def update_conversation(
    conversation_id: str,
    req: ConversationUpdate,
    user: dict = Depends(get_current_user),
):
    if req.title is None:
        raise HTTPException(status_code=400, detail="Nothing to update.")
    ok = await conv.rename_conversation(user["id"], conversation_id, req.title.strip())
    if not ok:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return {"status": "ok"}


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: str, user: dict = Depends(get_current_user)
):
    ok = await conv.delete_conversation(user["id"], conversation_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return {"status": "deleted"}
