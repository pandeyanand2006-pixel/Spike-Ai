"""Cloud speech-to-text fallback for devices without the Web Speech API (e.g. iOS)."""
from fastapi import APIRouter, Request

from app.config import get_settings
from app.services.ai_service import ai_service

router = APIRouter(prefix="/api/voice", tags=["voice"])


@router.post("/transcribe")
async def transcribe(request: Request):
    """Accept a raw audio body and return transcribed text via Groq Whisper.

    The browser sends the audio blob directly (not multipart) so no extra
    form-dependency is required. Auth is optional so guest users can use voice.
    """
    settings = get_settings()
    if not settings.groq_api_key:
        return {"text": ""}
    data = await request.body()
    if not data:
        return {"text": ""}
    content_type = request.headers.get("content-type", "audio/webm") or "audio/webm"
    text = await ai_service.transcribe(data, content_type)
    return {"text": text or ""}
