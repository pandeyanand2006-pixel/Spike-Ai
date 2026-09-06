"""Chat endpoints with streaming, tool routing, and optional persistence."""
import asyncio
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


def _to_dict(m):
    if isinstance(m, dict):
        return {"role": m.get("role"), "content": m.get("content", "")}
    return {"role": getattr(m, "role", "user"), "content": getattr(m, "content", "") or ""}


def _trim_messages(messages, max_messages: int = 14, max_chars: int = 1000):
    """Keep the recent context small enough to stay under Groq's free-tier request
    token limit (8000 tokens/request) so long chats don't trigger a 413."""
    msgs = [_to_dict(m) for m in messages]
    if len(msgs) > max_messages:
        msgs = msgs[-max_messages:]
    for m in msgs:
        if m["content"] and len(m["content"]) > max_chars:
            m["content"] = m["content"][:max_chars] + " …"
    return msgs


@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest, user: Optional[dict] = Depends(optional_current_user)):
    model = req.model or ai_service.default_model
    reply = await ai_service.complete(
        _trim_messages(req.messages), model=model, temperature=req.temperature
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
        stream_error = None
        try:
            if req.image:
                try:
                    text = await ai_service.vision_complete(
                        _last_user_text(req) or "Describe this image and help with it.",
                        req.image,
                    )
                except Exception as e:
                    # Don't close connection — stream the error as a token so UI can show it
                    err = getattr(e, "detail", str(e))
                    yield json.dumps({"token": f"\n\n[Error: {err}]"}) + "\n"
                    full.append(f"[Error: {err}]")
                    text = ""
                if text:
                    for chunk in text.split(" "):
                        tok = (chunk + " ") if chunk else " "
                        full.append(tok)
                        yield json.dumps({"token": tok}) + "\n"
            else:
                try:
                    async for token in ai_service.stream(
                        _trim_messages(req.messages), model=model, temperature=req.temperature
                    ):
                        if token:
                            full.append(token)
                            yield json.dumps({"token": token}) + "\n"
                except Exception as e:
                    # Groq TPD/rate-limit or any stream failure — keep connection open and stream error
                    msg = getattr(e, "detail", str(e))
                    if "ALL_MODELS_EXHAUSTED" in msg:
                        msg = "All models are at today's usage limit — try again later (resets at UTC midnight)."
                    stream_error = msg
                    yield json.dumps({"token": f"\n\n[Error: {msg}]"}) + "\n"
                    full.append(f"[Error: {msg}]")
        except asyncio.CancelledError:
            # Client closed connection (e.g., navigated away) — don't treat as server error
            raise
        except Exception as e:
            # Catch-all so connection is never torn down without a final frame
            msg = getattr(e, "detail", str(e))[:500]
            yield json.dumps({"error": msg}) + "\n"
            full.append(f"[Error: {msg}]")
        finally:
            try:
                if user is not None and cid is not None:
                    await conv.add_message(user["id"], cid, "assistant", "".join(full))
                    conv_obj = await conv.get_conversation(user["id"], cid)
                    if conv_obj and conv_obj.get("title") in (None, "New Chat"):
                        await generate_title(req.messages[0].content, cid, user["id"])
            except Exception:
                pass
            # Always send final frame so frontend doesn't see ERR_CONNECTION_CLOSED
            try:
                yield json.dumps({"conversationId": cid}) + "\n"
            except Exception:
                pass

    return StreamingResponse(
        event_generator(),
        media_type="application/x-ndjson",
        headers={
            "X-Conversation-Id": cid or "",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
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
