"""Agent request/response schemas."""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AgentRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000, description="User instruction for the agent")
    mode: str = Field("build", description="plan or build")
    model: Optional[str] = None
    sessionId: Optional[str] = None
    projectId: Optional[str] = Field(None, description="Project/workspace to operate in")
    forceApprove: bool = Field(False, description="Allow dangerous commands when true")


class AgentApproveRequest(BaseModel):
    sessionId: str
    tool: str
    input: Dict[str, Any]
    approve: bool = True


class AgentSessionOut(BaseModel):
    id: str
    title: str
    mode: str
    status: str
    createdAt: str
    updatedAt: str
    messageCount: int = 0


class AgentSessionDetail(BaseModel):
    id: str
    title: str
    mode: str
    status: str
    createdAt: str
    updatedAt: str
    messages: List[Dict[str, Any]] = []
    toolEvents: List[Dict[str, Any]] = []
    changedFiles: List[str] = []
