"""Chat endpoints with streaming and optional conversation persistence."""
import json
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.middleware.auth import optional_current_user
from app.models import conversation as conv
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.ai_service import ai_service
from app.services.conversation_service import (
    ensure_conversation,
    generate_title,
)

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest, user: Optional[dict] = Depends(optional_current_user)):
    model = req.model or ai_service.default_model

    reply = await ai_service.complete(
        req.messages,
        model=model,
        temperature=req.temperature,
    )

    # Persist only when authenticated
    if user is not None:
        conv_obj = await ensure_conversation(
            user["id"], req.conversationId, req.messages[0].content, model
        )
        cid = conv_obj["id"]
        await conv.add_message(user["id"], cid, "user", req.messages[-1].content)
        await conv.add_message(user["id"], cid, "assistant", reply)
        if conv_obj.get("title") in (None, "New Chat"):
            await generate_title(req.messages[0].content, cid, user["id"])

    return ChatResponse(reply=reply, model=model)


@router.post("/stream")
async def chat_stream(req: ChatRequest, user: Optional[dict] = Depends(optional_current_user)):
    model = req.model or ai_service.default_model

    # Resolve (or create) the backend conversation only when authenticated
    cid = None
    if user is not None:
        conv_obj = await ensure_conversation(
            user["id"], req.conversationId, req.messages[0].content, model
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
            if user is not None and cid is not None:
                await conv.add_message(user["id"], cid, "assistant", "".join(full))
                conv_obj = await conv.get_conversation(user["id"], cid)
                if conv_obj and conv_obj.get("title") in (None, "New Chat"):
                    await generate_title(req.messages[0].content, cid, user["id"])
            yield json.dumps({"conversationId": cid}) + "\n"

    return StreamingResponse(
        event_generator(),
        media_type="application/x-ndjson",
        headers={"X-Conversation-Id": cid or ""},
    )
