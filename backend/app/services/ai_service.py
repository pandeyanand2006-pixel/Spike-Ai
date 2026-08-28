"""AI service wrapping the Groq client."""
from typing import AsyncGenerator, List, Optional

from fastapi import HTTPException
from groq import AsyncGroq

from app.config import get_settings


class AIService:
    def __init__(self):
        settings = get_settings()
        self.client = AsyncGroq(api_key=settings.groq_api_key)
        self.default_model = settings.model

    @property
    def _api_key_present(self) -> bool:
        return bool(get_settings().groq_api_key)

    def build_history(self, messages: List[dict], system_prompt: str) -> List[dict]:
        history = [{"role": "system", "content": system_prompt}]
        for m in messages:
            role = "assistant" if m.get("role") == "bot" else m.get("role")
            if role not in ("user", "assistant"):
                continue
            history.append({"role": role, "content": m.get("content", "")})
        return history

    async def complete(
        self,
        messages: List[dict],
        model: Optional[str] = None,
        temperature: float = 0.7,
        system_prompt: Optional[str] = None,
    ) -> str:
        if not self._api_key_present:
            raise HTTPException(
                status_code=503, detail="AI service is not configured."
            )
        try:
            completion = await self.client.chat.completions.create(
                model=model or self.default_model,
                messages=self.build_history(messages, system_prompt or get_settings().system_prompt),
                temperature=temperature,
                max_tokens=4000,
            )
            return completion.choices[0].message.content or ""
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"AI service error: {e}")

    async def stream(
        self,
        messages: List[dict],
        model: Optional[str] = None,
        temperature: float = 0.7,
        system_prompt: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        if not self._api_key_present:
            raise HTTPException(
                status_code=503, detail="AI service is not configured."
            )
        try:
            stream = await self.client.chat.completions.create(
                model=model or self.default_model,
                messages=self.build_history(messages, system_prompt or get_settings().system_prompt),
                temperature=temperature,
                max_tokens=4000,
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except Exception as e:
            yield f"\n\n[Error: {e}]"


ai_service = AIService()
