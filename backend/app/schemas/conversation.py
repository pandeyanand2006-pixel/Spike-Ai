from typing import List, Optional

from pydantic import BaseModel, Field


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    createdAt: Optional[str] = None


class ConversationOut(BaseModel):
    id: str
    title: str
    createdAt: str
    updatedAt: str
    model: Optional[str] = None
    messages: List[MessageOut] = Field(default_factory=list)


class ConversationSummary(BaseModel):
    id: str
    title: str
    updatedAt: str
    model: Optional[str] = None


class ConversationUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=120)
