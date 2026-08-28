"""Conversation service: title generation and persistence."""
from typing import List, Optional

from app.models import conversation as conv
from app.services.ai_service import ai_service


def _candidate_title(first_user_message: str, max_len: int = 8) -> str:
    """Brute-force title from first words, usable offline."""
    words = first_user_message.split()
    if not words:
        return "New Chat"
    title = " ".join(words[:max_len])
    if len(title) > 60:
        title = title[:60].rsplit(" ", 1)[0]
    return title or "New Chat"


async def generate_title(first_user_message: str, conversation_id: str, user_id: str) -> str:
    """Try AI title generation; fall back to a short generated title."""
    try:
        reply = await ai_service.complete(
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Generate a short, useful 3-6 word conversation title for "
                        "this first user message. Return ONLY the title, no quotes, "
                        "no punctuation at the end:\n\n"
                        f"{first_user_message}"
                    ),
                }
            ],
            temperature=0.3,
            system_prompt=(
                "You are a title generator. Return only a concise title, "
                "3-6 words, no extra text."
            ),
        )
        title = reply.strip().strip('"').strip("'")[:120]
        if title:
            await conv.rename_conversation(user_id, conversation_id, title)
            return title
    except Exception:
        pass
    fallback = _candidate_title(first_user_message)
    await conv.rename_conversation(user_id, conversation_id, fallback)
    return fallback


async def ensure_conversation(
    user_id: str,
    conversation_id: Optional[str],
    first_user_message: str,
    model: str,
) -> dict:
    """Return an existing conversation or create a new one."""
    if conversation_id:
        existing = await conv.get_conversation(user_id, conversation_id)
        if existing:
            return existing
    return await conv.create_conversation(
        user_id, _candidate_title(first_user_message), model
    )
