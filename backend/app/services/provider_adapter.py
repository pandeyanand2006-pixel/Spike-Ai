"""Model/provider abstraction for Spike Agent.

Supports:
  groq            — Groq native (default, used by Chat)
  openrouter      — OpenRouter OpenAI-compat
  gemini          — Gemini via OpenAI-compat endpoint
  openai_compatible — any OpenAI-compat (Ollama, LM Studio, llama.cpp, local)

Remains backwards-compatible: Chat keeps using ai_service (Groq) directly;
Agent uses this adapter. Falls back gracefully when a provider is unavailable.
"""
import json
import os
import re
from typing import Any, Dict, List, Optional, AsyncGenerator

from app.config import get_settings


class LLMProvider:
    """Abstract provider — implement chat_with_tools."""
    name: str = "base"

    async def chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        model: str,
        temperature: float = 0.3,
        max_tokens: int = 900,
        stream: bool = True,
    ) -> tuple[str, List[Dict[str, Any]]]:
        raise NotImplementedError


# ---- Groq provider (wraps existing ai_service client with fallback logic) ----
class GroqProvider(LLMProvider):
    name = "groq"

    async def chat_with_tools(self, messages, tools, model, temperature=0.35, max_tokens=900, stream=True):
        # Reuse agent_service.call_llm_with_tools fallback logic by delegating to ai_service
        # but keep a minimal implementation here that mirrors agent_service's streaming.
        # To avoid circular import, we import lazily and reuse the low-level client.
        from app.services.ai_service import ai_service
        from app.config import get_settings as _gs
        settings = _gs()
        # Use the model's fallback chain via ai_service if needed
        # For simplicity, direct single-model call; fallback is handled at adapter level.
        client = ai_service.client
        try:
            if stream:
                stream_resp = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True,
                )
                content_acc = ""
                tool_acc: Dict[int, Dict[str, Any]] = {}
                async for chunk in stream_resp:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if getattr(delta, "content", None):
                        content_acc += delta.content
                    if getattr(delta, "tool_calls", None):
                        for tc in delta.tool_calls:
                            idx = getattr(tc, "index", 0) or 0
                            if idx not in tool_acc:
                                tool_acc[idx] = {"id": "", "name": "", "args": ""}
                            if getattr(tc, "id", None):
                                tool_acc[idx]["id"] = tc.id
                            func = getattr(tc, "function", None)
                            if func:
                                if getattr(func, "name", None):
                                    tool_acc[idx]["name"] += func.name
                                if getattr(func, "arguments", None):
                                    tool_acc[idx]["args"] += func.arguments
                tcs: List[Dict[str, Any]] = []
                for k in sorted(tool_acc.keys()):
                    e = tool_acc[k]
                    name = (e.get("name") or "").strip()
                    if not name:
                        continue
                    args_str = e.get("args") or "{}"
                    try:
                        args = json.loads(args_str) if args_str else {}
                    except Exception:
                        try:
                            args = json.loads(args_str + "}")
                        except Exception:
                            args = {}
                    tcs.append({"id": e.get("id") or f"call_{k}", "name": name, "arguments": args if isinstance(args, dict) else {}})
                return content_acc.strip(), tcs
            else:
                resp = await client.chat.completions.create(
                    model=model, messages=messages, tools=tools, tool_choice="auto", temperature=temperature, max_tokens=max_tokens
                )
                m = resp.choices[0].message
                text = (m.content or "").strip()
                tcs = []
                if getattr(m, "tool_calls", None):
                    for tc in m.tool_calls:
                        try:
                            args = json.loads(tc.function.arguments or "{}")
                        except Exception:
                            args = {}
                        tcs.append({"id": tc.id, "name": tc.function.name, "arguments": args if isinstance(args, dict) else {}})
                return text, tcs
        except Exception as e:
            raise e


# ---- OpenAI-compatible provider (covers OpenRouter, Ollama, LM Studio, generic) ----
class OpenAICompatibleProvider(LLMProvider):
    name = "openai_compatible"

    def __init__(self, base_url: str, api_key: str = ""):
        self.base_url = (base_url or "").rstrip("/") or None
        self.api_key = api_key or "ollama"  # Ollama doesn't need a key

    async def chat_with_tools(self, messages, tools, model, temperature=0.35, max_tokens=900, stream=True):
        # Use openai Async client with custom base
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise RuntimeError("openai package required for openai_compatible provider (pip install openai)")
        if not self.base_url:
            raise RuntimeError("OPENAI_COMPATIBLE_BASE_URL / OLLAMA_BASE_URL not set")
        # Map tool schemas: OpenAI expects same shape as Groq
        client = AsyncOpenAI(base_url=self.base_url, api_key=self.api_key)
        # For Ollama local, the default model is often llama3/qwen; allow override
        # Try streaming then fallback to non-stream
        try:
            if stream:
                stream_resp = await client.chat.completions.create(
                    model=model, messages=messages, tools=tools, tool_choice="auto", temperature=temperature, max_tokens=max_tokens, stream=True
                )
                content_acc = ""
                tool_acc: Dict[int, Dict[str, Any]] = {}
                async for chunk in stream_resp:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if getattr(delta, "content", None):
                        content_acc += delta.content
                    if getattr(delta, "tool_calls", None):
                        for tc in delta.tool_calls:
                            idx = getattr(tc, "index", 0) or 0
                            if idx not in tool_acc:
                                tool_acc[idx] = {"id": "", "name": "", "args": ""}
                            if getattr(tc, "id", None):
                                tool_acc[idx]["id"] = tc.id
                            func = getattr(tc, "function", None)
                            if func:
                                if getattr(func, "name", None):
                                    tool_acc[idx]["name"] += func.name
                                if getattr(func, "arguments", None):
                                    tool_acc[idx]["args"] += func.arguments
                tcs: List[Dict[str, Any]] = []
                for k in sorted(tool_acc.keys()):
                    e = tool_acc[k]
                    name = (e.get("name") or "").strip()
                    if not name:
                        continue
                    args_str = e.get("args") or "{}"
                    try:
                        args = json.loads(args_str) if args_str else {}
                    except Exception:
                        args = {}
                    tcs.append({"id": e.get("id") or f"call_{k}", "name": name, "arguments": args if isinstance(args, dict) else {}})
                return content_acc.strip(), tcs
            else:
                resp = await client.chat.completions.create(
                    model=model, messages=messages, tools=tools, tool_choice="auto", temperature=temperature, max_tokens=max_tokens
                )
                m = resp.choices[0].message
                text = (m.content or "").strip()
                tcs = []
                if getattr(m, "tool_calls", None):
                    for tc in m.tool_calls:
                        try:
                            args = json.loads(tc.function.arguments or "{}")
                        except Exception:
                            args = {}
                        tcs.append({"id": tc.id, "name": tc.function.name, "arguments": args if isinstance(args, dict) else {}})
                return text, tcs
        except Exception as e:
            raise e


# ---- Factory / router ----
def _provider_from_settings() -> tuple[LLMProvider, str]:
    """Return (provider_instance, model) per settings. Never breaks Chat — Agent only."""
    s = get_settings()
    provider_name = (os.getenv("LLM_PROVIDER", "") or "").strip().lower()
    # Also check config's model/provider abstraction
    # Preference: explicit env LLM_PROVIDER, else legacy GROQ path
    # Detect Ollama locally
    ollama_url = os.getenv("OLLAMA_BASE_URL", "") or os.getenv("OPENAI_COMPATIBLE_BASE_URL", "")
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    compat_key = os.getenv("OPENAI_COMPATIBLE_API_KEY", "") or os.getenv("OPENROUTER_API_KEY", "")
    compat_url = os.getenv("OPENAI_COMPATIBLE_BASE_URL", "") or ollama_url

    # If explicit groq (default)
    if not provider_name or provider_name == "groq":
        if getattr(s, "groq_api_key", ""):
            return GroqProvider(), s.model
        # If groq key missing but compat available, fall back to compat if configured
        if compat_url:
            return OpenAICompatibleProvider(base_url=compat_url, api_key=compat_key or s.groq_api_key), s.model
        return GroqProvider(), s.model  # will error gracefully in provider

    if provider_name == "openrouter":
        base = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        key = openrouter_key or s.groq_api_key
        return OpenAICompatibleProvider(base_url=base, api_key=key), os.getenv("OPENROUTER_MODEL", s.model)

    if provider_name == "gemini":
        # Gemini via OpenRouter or direct OpenAI-compat shim
        base = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
        key = gemini_key
        return OpenAICompatibleProvider(base_url=base, api_key=key), os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

    if provider_name in ("openai_compatible", "openai", "ollama", "lm_studio", "local"):
        base = compat_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        model = os.getenv("OLLAMA_MODEL", "") or os.getenv("OPENAI_COMPATIBLE_MODEL", "") or s.model
        # if Ollama default, prefer a generic lightweight model if not set
        if provider_name == "ollama" and not os.getenv("OLLAMA_MODEL"):
            model = os.getenv("OLLAMA_MODEL", "llama3.1") or model
        return OpenAICompatibleProvider(base_url=base, api_key=compat_key or "ollama"), model

    # fallback to groq
    return GroqProvider(), s.model


def get_agent_provider() -> tuple[LLMProvider, str]:
    return _provider_from_settings()


def is_local_provider_available(timeout: float = 2.0) -> bool:
    """Check if a local Ollama / OpenAI-compat endpoint is reachable (no GPU required)."""
    import httpx
    urls = [
        os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        os.getenv("OPENAI_COMPATIBLE_BASE_URL", ""),
    ]
    for u in urls:
        if not u:
            continue
        probe = u.rstrip("/")  # try /models
        try:
            # Ollama health is at / (GET), OpenAI compat at /models
            candidates = [probe + "/models", probe.replace("/v1", "")]
            for cand in candidates:
                try:
                    r = httpx.get(cand, timeout=timeout)
                    if r.status_code < 500:
                        return True
                except Exception:
                    continue
        except Exception:
            continue
    return False
