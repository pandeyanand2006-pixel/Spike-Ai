from typing import List, Optional

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: List[Message] = Field(..., min_length=1)
    temperature: Optional[float] = 0.7
    model: Optional[str] = None
    conversationId: Optional[str] = None
    mode: Optional[str] = None  # "chat" | "image" | "ppt"
    image: Optional[str] = None  # base64 data URL of an attached image


class ChatResponse(BaseModel):
    reply: str
    model: str
