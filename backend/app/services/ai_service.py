"""AI service wrapping the Groq client."""
import json
import re
from typing import AsyncGenerator, List, Optional

import httpx
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
            # Accept both Pydantic Message objects and plain dicts
            if isinstance(m, dict):
                role = "assistant" if m.get("role") == "bot" else m.get("role")
                content = m.get("content", "")
            else:
                role = "assistant" if getattr(m, "role", "") == "bot" else getattr(m, "role", "")
                content = getattr(m, "content", "") or ""
            if role not in ("user", "assistant"):
                continue
            history.append({"role": role, "content": content})
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
                max_tokens=900,
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
                max_tokens=900,
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except Exception as e:
            yield f"\n\n[Error: {e}]"

    async def vision_complete(
        self, text: str, image_data_url: str, max_tokens: int = 2000
    ) -> str:
        """Answer a text prompt that includes an attached image (vision)."""
        settings = get_settings()
        url = settings.vision_base_url.rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if settings.vision_api_key:
            headers["Authorization"] = "Bearer " + settings.vision_api_key
        payload = {
            "model": settings.vision_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": text},
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                    ],
                }
            ],
            "max_tokens": max_tokens,
        }
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
            return data["choices"][0]["message"]["content"] or ""
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Image understanding is unavailable. Set VISION_BASE_URL / "
                    "VISION_API_KEY (e.g. an OpenAI-compatible vision endpoint) to enable it. ("
                    + str(e)[:120]
                    + ")"
                ),
            )

    async def transcribe(self, audio_bytes: bytes, content_type: str = "audio/webm") -> str:
        """Transcribe audio via Groq Whisper (used as a fallback when the browser
        Web Speech API is unavailable, e.g. iOS Safari)."""
        if not self._api_key_present:
            return ""
        ct = (content_type or "").lower()
        if "mp4" in ct or "m4a" in ct:
            fname = "audio.mp4"
        elif "ogg" in ct:
            fname = "audio.ogg"
        elif "wav" in ct:
            fname = "audio.wav"
        else:
            fname = "audio.webm"
        last_err = ""
        for model in ("whisper-large-v3-turbo", "whisper-large-v3"):
            try:
                resp = await self.client.audio.transcriptions.create(
                    model=model,
                    file=(fname, audio_bytes, content_type or "audio/webm"),
                    language="en",
                )
                return getattr(resp, "text", "") or ""
            except Exception as e:  # try next model
                last_err = str(e)
        return ""

    async def outline_presentation(self, topic: str, slides: int = 6):
        """Use the LLM to produce a structured presentation outline as JSON."""
        sys = (
            "You are a presentation designer. Given a topic, return ONLY valid JSON: "
            "a list of slide objects, each with 'title' (string) and 'bullets' (list of "
            "short strings, 3-6 each). Do not include markdown or commentary."
        )
        user = (
            f"Create a {slides}-slide presentation outline about: {topic}\n"
            "Return JSON only."
        )
        raw = await self.complete(
            [{"role": "user", "content": user}],
            temperature=0.6,
            system_prompt=sys,
        )
        try:
            raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.I).strip()
            data = json.loads(raw)
            if isinstance(data, dict):
                data = data.get("slides", data.get("outline", []))
            return [d for d in data if isinstance(d, dict) and d.get("title")]
        except Exception:
            # Fallback: a single slide with the topic
            return [{"title": topic, "bullets": ["Overview", "Key points", "Summary"]}]


def detect_tool(text: str) -> Optional[str]:
    """Lightweight intent detection for image / ppt generation from free text."""
    t = (text or "").lower()
    if re.search(
        r"\b(generate|create|make|draw|produce|render|design)\b.{0,25}"
        r"\b(image|picture|photo|art|illustration|drawing|wallpaper|logo|poster)\b",
        t,
    ):
        return "image"
    if re.search(
        r"\b(make|create|build|generate|prepare|give me|write|draft)\b.{0,30}"
        r"\b(ppt|presentation|slides?|powerpoint|deck|pdf|document|report|essay|article|whitepaper)\b",
        t,
    ):
        return "ppt"
    if re.search(r"\bpresentation\b.{0,20}\b(on|about|for)\b", t):
        return "ppt"
    return None


ai_service = AIService()
