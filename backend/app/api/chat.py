"""Chat endpoints with streaming, tool routing, and optional persistence."""
import json
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.middleware.auth import optional_current_user
from app.models import conversation as conv
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.ai_service import ai_service, detect_tool
from app.services import tools_service
from app.services.conversation_service import (
    ensure_conversation,
    generate_title,
)

router = APIRouter(prefix="/api/chat", tags=["chat"])

TOOL_SENTINEL = "__TOOL__::"


def _last_user_text(req: ChatRequest) -> str:
    for m in reversed(req.messages):
        if m.role == "user" and m.content:
            return m.content
    return ""


@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest, user: Optional[dict] = Depends(optional_current_user)):
    model = req.model or ai_service.default_model
    reply = await ai_service.complete(
        req.messages, model=model, temperature=req.temperature
    )
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

    # ----- Tool routing -----
    mode = req.mode if req.mode in ("image", "ppt") else None
    if not mode and not req.image:
        mode = detect_tool(_last_user_text(req))

    if mode == "image":
        return await _tool_stream(
            _image_tool, _last_user_text(req), req, user, model
        )
    if mode == "ppt":
        return await _tool_stream(
            _ppt_tool, _last_user_text(req), req, user, model
        )

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
            if req.image:
                # Vision: understand the attached image, then answer.
                text = await ai_service.vision_complete(
                    _last_user_text(req) or "Describe this image and help with it.",
                    req.image,
                )
                for chunk in text.split(" "):
                    tok = (chunk + " ") if chunk else " "
                    full.append(tok)
                    yield json.dumps({"token": tok}) + "\n"
            else:
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


async def _tool_stream(fn, prompt, req, user, model):
    """Run a generator tool (image/ppt) and stream a single tool event."""
    cid = None
    if user is not None:
        conv_obj = await ensure_conversation(
            user["id"], req.conversationId, prompt or "tool", model
        )
        cid = conv_obj["id"]
        await conv.add_message(user["id"], cid, "user", prompt)

    async def event_generator():
        try:
            tool = await fn(prompt)
            yield json.dumps({"tool": tool}) + "\n"
            if user is not None and cid is not None:
                await conv.add_message(
                    user["id"], cid, "assistant", TOOL_SENTINEL + json.dumps(tool)
                )
        except Exception as e:
            msg = getattr(e, "detail", str(e))
            yield json.dumps({"error": msg}) + "\n"
        finally:
            yield json.dumps({"conversationId": cid}) + "\n"

    return StreamingResponse(
        event_generator(),
        media_type="application/x-ndjson",
        headers={"X-Conversation-Id": cid or ""},
    )


async def _image_tool(prompt: str) -> dict:
    url = await tools_service.generate_image(prompt)
    return {"type": "image", "url": url, "prompt": prompt}


async def _ppt_tool(prompt: str) -> dict:
    return await tools_service.generate_ppt(prompt)
