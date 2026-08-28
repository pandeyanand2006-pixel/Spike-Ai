"""Health and model listing endpoints."""
from fastapi import APIRouter

from app.config import get_settings
from app.db import ping
from app.services.ai_service import ai_service

router = APIRouter(tags=["meta"])


@router.get("/api/health")
async def health():
    settings = get_settings()
    db_ok = await ping()
    return {
        "status": "ok",
        "ai": "available" if settings.groq_api_key else "missing_api_key",
        "database": "connected" if db_ok else "unavailable",
        "model": settings.model,
    }


@router.get("/api/models")
async def models():
    if not get_settings().groq_api_key:
        return {"models": []}
    try:
        data = await ai_service.client.models.list()
        ids = sorted(
            m.id
            for m in data.data
            if not any(
                x in m.id
                for x in ("whisper", "prompt-guard", "safeguard",
                          "orpheus", "compound", "gpt-oss")
            )
        )
        return {"models": ids}
    except Exception:
        return {"models": []}
