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
        self._daily_exhausted: dict = {}

    @property
    def _api_key_present(self) -> bool:
        return bool(get_settings().groq_api_key)

    def _is_exhausted(self, model: str) -> bool:
        import time as _time
        exp = self._daily_exhausted.get(model)
        if exp is None:
            return False
        if _time.time() < exp:
            return True
        self._daily_exhausted.pop(model, None)
        return False

    def _mark_exhausted(self, model: str, err_text: str):
        import time as _time
        from datetime import datetime, timezone as _tz, timedelta as _td
        low = (err_text or "").lower()
        is_tpd = "tokens per day" in low or " tpd" in low
        if is_tpd:
            now = datetime.now(_tz.utc)
            nxt = now.replace(hour=0, minute=0, second=0, microsecond=0) + _td.timedelta(days=1)
            self._daily_exhausted[model] = nxt.timestamp()
        elif "tokens per minute" in low or "tpm" in low or "rate_limit" in low or "429" in low:
            self._daily_exhausted[model] = _time.time() + 65

    def _is_model_error(self, err_text: str) -> bool:
        low = (err_text or "").lower()
        return "model_not_found" in low or "decommissioned" in low or "does not exist" in low or "model_not_found" in low

    def _fallback_chain(self, model: Optional[str]) -> list:
        settings = get_settings()
        chain = list(getattr(settings, "model_fallback_chain", [settings.model]))
        if model and model not in chain:
            chain = [model] + [m for m in chain if m != model]
        return [m for m in chain if not self._is_exhausted(m)] or chain

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
        chain = self._fallback_chain(model)
        last_err = None
        for mdl in chain:
            try:
                completion = await self.client.chat.completions.create(
                    model=mdl,
                    messages=self.build_history(messages, system_prompt or get_settings().system_prompt),
                    temperature=temperature,
                    max_tokens=900,
                )
                return completion.choices[0].message.content or ""
            except Exception as e:
                last_err = str(e)
                if self._is_model_error(last_err):
                    # model doesn't exist for this key — try next in chain immediately
                    continue
                is_rl = "429" in last_err or "rate_limit" in last_err.lower()
                if is_rl:
                    self._mark_exhausted(mdl, last_err)
                    if "tokens per day" in last_err.lower() or "tpd" in last_err.lower():
                        continue
                    # per-minute: wait once then try next model
                    import asyncio as _aio
                    try:
                        await _aio.sleep(7)
                    except Exception:
                        pass
                    continue
                raise HTTPException(status_code=502, detail=f"AI service error: {e}")
        # all exhausted
        if last_err and ("tokens per day" in last_err.lower() or "tpd" in last_err.lower()):
            raise HTTPException(status_code=503, detail="ALL_MODELS_EXHAUSTED: All models are at today's usage limit — try again later")
        # if last was model_not_found, surface that clearly
        if last_err and self._is_model_error(last_err):
            raise HTTPException(status_code=502, detail=f"AI service error: {last_err}")
        raise HTTPException(status_code=502, detail=f"AI service error: {last_err}")

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
        chain = self._fallback_chain(model)
        last_err = None
        for mdl in chain:
            try:
                stream = await self.client.chat.completions.create(
                    model=mdl,
                    messages=self.build_history(messages, system_prompt or get_settings().system_prompt),
                    temperature=temperature,
                    max_tokens=900,
                    stream=True,
                )
                async for chunk in stream:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yield delta
                return
            except Exception as e:
                last_err = str(e)
                if self._is_model_error(last_err):
                    continue
                is_rl = "429" in last_err or "rate_limit" in last_err.lower()
                if is_rl:
                    self._mark_exhausted(mdl, last_err)
                    if "tokens per day" in last_err.lower() or "tpd" in last_err.lower():
                        continue
                    import asyncio as _aio
                    try:
                        await _aio.sleep(7)
                    except Exception:
                        pass
                    continue
                yield f"\n\n[Error: {e}]"
                return
        if last_err and ("tokens per day" in last_err.lower() or "tpd" in last_err.lower()):
            yield "\n\n[ALL_MODELS_EXHAUSTED: All models are at today's usage limit — try again later]"
        elif last_err and self._is_model_error(last_err):
            yield f"\n\n[Error: {last_err}]"
        elif last_err:
            yield f"\n\n[Error: {last_err}]"

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
