"""Project schemas."""
from typing import Optional

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    description: Optional[str] = Field(None, max_length=300)
    template: Optional[str] = Field("other", description="react|nextjs|node|python|fastapi|html|other")


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=80)
    description: Optional[str] = Field(None, max_length=300)


class ProjectOut(BaseModel):
    id: str
    name: str
    description: str = ""
    template: str = "other"
    stack: str = ""
    workspace: str = ""
    createdAt: str
    updatedAt: str
    lastOpenedAt: str = ""
    status: str = "ready"
