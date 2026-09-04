"""Agent API — streaming NDJSON agent execution + session management."""
import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.middleware.auth import get_current_user, optional_current_user
from app.models import agent_session as agent_store
from app.models import project as project_model
from app.schemas.agent import AgentRequest
from app.services.agent_service import stream_agent_loop
from app.services.agent_tools import WORKSPACE as DEFAULT_WORKSPACE
from app.services.workspace_service import get_workspace as get_project_workspace

router = APIRouter(prefix="/api/agent", tags=["agent"])


def _short_title(msg: str) -> str:
    t = (msg or "Agent Session").strip().splitlines()[0][:60]
    # Title-case first words, keep concise
    words = t.split()[:6]
    return " ".join(words)[:60] or "Agent Session"


@router.get("/sessions")
async def list_sessions(
    projectId: Optional[str] = Query(None, description="Filter by project"),
    user: dict = Depends(get_current_user),
):
    items = await agent_store.list_agent_sessions(user["id"], project_id=projectId)
    return items


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, user: dict = Depends(get_current_user)):
    doc = await agent_store.get_agent_session(user["id"], session_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Agent session not found.")
    return {
        "id": doc["id"],
        "title": doc.get("title", "Agent Session"),
        "mode": doc.get("mode", "build"),
        "status": doc.get("status", "active"),
        "createdAt": doc.get("createdAt", ""),
        "updatedAt": doc.get("updatedAt", ""),
        "messages": doc.get("messages", []),
        "toolEvents": doc.get("toolEvents", []),
        "changedFiles": doc.get("changedFiles", []),
    }


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, user: dict = Depends(get_current_user)):
    ok = await agent_store.delete_agent_session(user["id"], session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Agent session not found.")
    return {"status": "deleted"}


@router.post("/stream")
async def agent_stream(req: AgentRequest, user: Optional[dict] = Depends(optional_current_user)):
    mode = req.mode if req.mode in ("plan", "build") else "build"

    # Resolve project workspace if projectId provided
    workspace: Path | None = None
    project_info: dict | None = None
    project_id = req.projectId
    if project_id and user is not None:
        pdoc = await project_model.get_project(user["id"], project_id)
        if pdoc is None:
            raise HTTPException(status_code=404, detail="Project not found.")
        try:
            workspace = get_project_workspace(user["id"], project_id)
            workspace.mkdir(parents=True, exist_ok=True)
            project_info = {
                "name": pdoc.get("name", ""),
                "description": pdoc.get("description", ""),
                "template": pdoc.get("template", ""),
                "stack": pdoc.get("stack", ""),
                "workspace": str(workspace),
            }
            # touch lastOpened
            await project_model.touch_project(user["id"], project_id)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Workspace error: {e}")
    elif project_id and user is None:
        # Guest with projectId: still try to resolve (for demo)
        try:
            workspace = get_project_workspace("guest", project_id)
            project_info = {"name": "Guest Project", "workspace": str(workspace), "stack": "", "template": ""}
        except Exception:
            workspace = None
    else:
        # No project — fall back to default repo workspace (backwards compat)
        workspace = DEFAULT_WORKSPACE
        project_info = None

    # Resolve or create session (now project-scoped)
    session_id = req.sessionId
    is_guest = user is None
    uid = user["id"] if user else "guest"

    if session_id and not is_guest:
        sess = await agent_store.get_agent_session(uid, session_id)
        if sess is None:
            title = _short_title(req.message)
            sess = await agent_store.create_agent_session(uid, title, mode, project_id=project_id)
            session_id = sess["id"]
        else:
            session_id = sess["id"]
    elif not is_guest:
        title = _short_title(req.message)
        sess = await agent_store.create_agent_session(uid, title, mode, project_id=project_id)
        session_id = sess["id"]
    else:
        session_id = session_id or "guest-" + _short_title(req.message).replace(" ", "-").lower()

    if not is_guest:
        await agent_store.append_agent_message(uid, session_id, "user", req.message)
    history = []
    if not is_guest:
        doc = await agent_store.get_agent_session(uid, session_id)
        if doc:
            history = doc.get("messages", [])[:-1]

    async def event_generator():
        yield json.dumps({"type": "session_started", "sessionId": session_id, "mode": mode, "title": _short_title(req.message), "projectId": project_id}) + "\n"
        # Also inform frontend of project context
        if project_info:
            yield json.dumps({"type": "project_loaded", "projectId": project_id, "project": project_info}) + "\n"
        full_assistant = []
        changed: list[str] = []
        try:
            async for ev in stream_agent_loop(
                user_message=req.message, mode=mode, model=req.model, history=history, workspace=workspace, project_info=project_info
            ):
                # persist tool events / changed files
                if not is_guest and ev.get("type") in ("tool_start", "tool_result", "command_started", "command_result", "file_changed", "approval_required"):
                    await agent_store.append_tool_event(uid, session_id, ev)
                if ev.get("type") == "file_changed" and ev.get("path"):
                    if ev["path"] not in changed:
                        changed.append(ev["path"])
                if ev.get("type") == "completed" and ev.get("content"):
                    full_assistant.append(ev["content"])
                yield json.dumps(ev) + "\n"
        except Exception as e:
            yield json.dumps({"type": "error", "message": str(e)[:500]}) + "\n"
        finally:
            if not is_guest and full_assistant:
                txt = "\n".join(full_assistant)
                await agent_store.append_agent_message(uid, session_id, "assistant", txt[:10000])
                if changed:
                    await agent_store.mark_changed_files(uid, session_id, changed)
                await agent_store.update_agent_status(uid, session_id, "completed")
            yield json.dumps({"type": "session_ended", "sessionId": session_id, "changedFiles": changed}) + "\n"

    return StreamingResponse(event_generator(), media_type="application/x-ndjson", headers={"X-Agent-Session-Id": session_id})
