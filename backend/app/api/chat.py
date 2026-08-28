"""Chat endpoints with streaming and conversation persistence."""
import json
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.middleware.auth import get_current_user
from app.models import conversation as conv
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.ai_service import ai_service
from app.services.conversation_service import (
    ensure_conversation,
    generate_title,
)

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _history_with_saved(messages, conversation_id, user_id):
    """Build context from persisted messages + the incoming request."""
    history = [{"role": m.get("role"), "content": m.get("content")}
               for m in messages]
    return history


@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest, user: dict = Depends(get_current_user)):
    model = req.model or ai_service.default_model
    conv_obj = await ensure_conversation(
        user["id"], req.conversationId,
        req.messages[0].content, model,
    )
    cid = conv_obj["id"]

    await conv.add_message(user["id"], cid, "user", req.messages[-1].content)

    reply = await ai_service.complete(
        req.messages,
        model=model,
        temperature=req.temperature,
    )

    await conv.add_message(user["id"], cid, "assistant", reply)

    if conv_obj.get("title") in (None, "New Chat"):
        await generate_title(req.messages[0].content, cid, user["id"])

    return ChatResponse(reply=reply, model=model)


@router.post("/stream")
async def chat_stream(req: ChatRequest, user: dict = Depends(get_current_user)):
    model = req.model or ai_service.default_model
    conv_obj = await ensure_conversation(
        user["id"], req.conversationId,
        req.messages[0].content, model,
    )
    cid = conv_obj["id"]
    await conv.add_message(user["id"], cid, "user", req.messages[-1].content)

    async def event_generator():
        full = []
        try:
            async for token in ai_service.stream(
                req.messages, model=model, temperature=req.temperature
            ):
                if token:
                    full.append(token)
                    yield json.dumps({"token": token}) + "\n"
        finally:
            reply = "".join(full)
            if reply:
                await conv.add_message(user["id"], cid, "assistant", reply)
            if conv_obj.get("title") in (None, "New Chat"):
                await generate_title(req.messages[0].content, cid, user["id"])
                # yield a final update so the client can refresh the sidebar title
                yield json.dumps({"conversationId": cid}) + "\n"

    return StreamingResponse(
        event_generator(),
        media_type="application/x-ndjson",
        headers={"X-Conversation-Id": cid},
    )
