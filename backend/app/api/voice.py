"""Cloud speech-to-text fallback for devices without the Web Speech API (e.g. iOS)."""
from fastapi import APIRouter, File, UploadFile

from app.config import get_settings
from app.services.ai_service import ai_service

router = APIRouter(prefix="/api/voice", tags=["voice"])


@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    """Accept an audio blob and return transcribed text via Groq Whisper.

    Auth is optional so guest users can also use voice input.
    """
    settings = get_settings()
    if not settings.groq_api_key:
        return {"text": ""}
    data = await file.read()
    if not data:
        return {"text": ""}
    text = await ai_service.transcribe(data, file.content_type or "audio/webm")
    return {"text": text or ""}
