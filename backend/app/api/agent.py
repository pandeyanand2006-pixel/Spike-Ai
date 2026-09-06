"""Agent API — streaming NDJSON agent execution + session management.

Phases:
1. Native tool calling (STREAM uses tool_schemas)
2. Todos (todo_update + /build)
3. Approval pause + approve/continue
4. Tool parity checked via _assert_tool_parity in agent_service
6. Formalized NDJSON event vocabulary
"""
import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.middleware.auth import get_current_user, optional_current_user
from app.models import agent_session as agent_store
from app.models import project as project_model
from app.schemas.agent import AgentRequest
from app.services.agent_service import stream_agent_loop
from app.services.workspace_service import get_workspace as get_project_workspace

router = APIRouter(prefix="/api/agent", tags=["agent"])


def _short_title(msg: str) -> str:
    t = (msg or "Agent Session").strip().splitlines()[0][:60]
    words = t.split()[:6]
    return " ".join(words)[:60] or "Agent Session"


@router.get("/sessions")
async def list_sessions(
    projectId: Optional[str] = Query(None, description="Filter by project"),
    user: Optional[dict] = Depends(optional_current_user),
):
    import asyncio
    if user is None:
        # Guest / unauthenticated — return empty so frontend doesn't see 401 console errors
        return []
    try:
        if projectId in (None, "", "null", "undefined", "NaN"):
            projectId = None
        items = await asyncio.wait_for(
            agent_store.list_agent_sessions(user["id"], project_id=projectId),
            timeout=8.0,
        )
        return items
    except asyncio.TimeoutError:
        import logging
        logging.getLogger("uvicorn.error").error("GET /api/agent/sessions timed out (DB slow)")
        raise HTTPException(status_code=503, detail="Database temporarily unavailable. Please retry.")
    except HTTPException:
        raise
    except Exception as e:
        import logging, traceback
        logging.getLogger("uvicorn.error").error(f"GET /api/agent/sessions failed: {e}\n{traceback.format_exc()}")
        return []


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
        "todos": doc.get("todos", []),
        "pendingApproval": doc.get("pendingApproval"),
        "inspected": doc.get("inspected", False),
        "projectId": str(doc.get("projectId")) if doc.get("projectId") else None,
    }


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, user: dict = Depends(get_current_user)):
    ok = await agent_store.delete_agent_session(user["id"], session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Agent session not found.")
    return {"status": "deleted"}


@router.post("/sessions/{session_id}/stop")
async def stop_session(session_id: str, user: dict = Depends(get_current_user)):
    doc = await agent_store.get_agent_session(user["id"], session_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Agent session not found.")
    await agent_store.update_agent_status(user["id"], session_id, "stopped")
    return {"status": "stopped", "sessionId": session_id}


class ApproveBody(BaseModel):
    approve: bool = True


@router.post("/sessions/{session_id}/approve")
async def approve_session(session_id: str, body: ApproveBody, user: dict = Depends(get_current_user)):
    """Approve or deny a pending dangerous tool (Phase 3)."""
    doc = await agent_store.get_agent_session(user["id"], session_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Agent session not found.")
    pending = doc.get("pendingApproval")
    if not pending:
        raise HTTPException(status_code=400, detail="No pending approval.")
    tool = pending.get("tool")
    inp = pending.get("input", {})
    # Clear pending first
    await agent_store.update_pending_approval(user["id"], session_id, None)
    if not body.approve:
        # Feed denial as tool result and resume loop with denial message
        # Persist a tool event for UI
        await agent_store.append_tool_event(user["id"], session_id, {"type": "tool_result", "tool": tool, "success": False, "output": "User denied approval — proposal rejected. Propose a safer alternative."})
        await agent_store.append_agent_message(user["id"], session_id, "user", f"User declined to approve {tool} {json.dumps(inp)}. Propose a safer alternative.")
        await agent_store.update_agent_status(user["id"], session_id, "active")
        return {"status": "denied", "sessionId": session_id}
    # Approved: execute the pending tool now
    # Resolve workspace
    project_id = str(doc.get("projectId")) if doc.get("projectId") else None
    workspace: Path | None = None
    project_info: dict | None = None
    if project_id:
        try:
            pdoc = await project_model.get_project(user["id"], project_id)
            if pdoc:
                workspace = get_project_workspace(user["id"], project_id)
                workspace.mkdir(parents=True, exist_ok=True)
                project_info = {"name": pdoc.get("name", ""), "workspace": str(workspace), "stack": pdoc.get("stack", ""), "template": pdoc.get("template", "")}
        except Exception:
            pass
    # Execute via appropriate executor
    is_local = False
    if project_info:
        from app.services.workspace_service import is_local_workspace
        is_local = is_local_workspace(project_info.get("workspace", ""))
    result: dict
    if is_local and project_id:
        from app.api.bridge import forward_tool_to_bridge
        tmo = 60.0 if tool == "run_command" else 30.0
        result = await forward_tool_to_bridge(user["id"], project_id, tool, inp, timeout=tmo)
    else:
        from app.services.agent_service import execute_tool
        result = await execute_tool(tool, inp, mode="build", workspace=workspace, project_info=project_info)
    await agent_store.append_tool_event(user["id"], session_id, {"type": "tool_result", "tool": tool, "success": result.get("success", False), "output": result.get("output", "")[:5000]})
    # Store tool result as a tool message for history replay
    await agent_store.append_agent_message(user["id"], session_id, "assistant", "", extra={"tool_calls": [{"id": pending.get("id", "approved"), "type": "function", "function": {"name": tool, "arguments": json.dumps(inp)}}]})
    await agent_store.append_agent_message(user["id"], session_id, "tool", result.get("output", "")[:3000], extra={"tool_call_id": pending.get("id", "approved")})
    if tool in ("write_file", "edit_file", "create_directory", "move_file") and result.get("success"):
        p = inp.get("path") or inp.get("src")
        if p:
            await agent_store.mark_changed_files(user["id"], session_id, [p])
            await agent_store.append_tool_event(user["id"], session_id, {"type": "file_changed", "path": p})
    await agent_store.update_agent_status(user["id"], session_id, "active")
    return {"status": "approved", "result": result, "sessionId": session_id}


@router.post("/sessions/{session_id}/continue")
async def continue_session(session_id: str, user: dict = Depends(get_current_user)):
    """Resume a stopped/error/step-limited session (Phase 3). Returns streaming NDJSON."""
    doc = await agent_store.get_agent_session(user["id"], session_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Agent session not found.")
    status = doc.get("status", "active")
    if status == "completed":
        raise HTTPException(status_code=400, detail="Session already completed — cannot continue")
    # allow active, stopped, error, or any non-completed
    project_id = str(doc.get("projectId")) if doc.get("projectId") else None
    if not project_id:
        raise HTTPException(status_code=400, detail="Session has no project.")
    pdoc = await project_model.get_project(user["id"], project_id)
    if pdoc is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    workspace = get_project_workspace(user["id"], project_id)
    workspace.mkdir(parents=True, exist_ok=True)
    project_info = {"name": pdoc.get("name", ""), "description": pdoc.get("description", ""), "template": pdoc.get("template", ""), "stack": pdoc.get("stack", ""), "workspace": str(workspace)}
    await project_model.touch_project(user["id"], project_id)
    history = doc.get("messages", [])
    existing_todos = doc.get("todos", [])
    # Flip status to active
    await agent_store.update_agent_status(user["id"], session_id, "active")

    async def event_generator():
        yield json.dumps({"type": "session_started", "sessionId": session_id, "mode": doc.get("mode", "build"), "title": doc.get("title", "Agent Session"), "projectId": project_id}) + "\n"
        yield json.dumps({"type": "project_loaded", "projectId": project_id, "project": project_info}) + "\n"
        full_assistant = []
        changed: list[str] = []
        had_error = False
        error_msg = ""
        try:
            async for ev in stream_agent_loop(
                user_message="Continue where you left off. Resume the task.",
                mode=doc.get("mode", "build"),
                model=None,
                history=history,
                workspace=workspace,
                project_info=project_info,
                user_id=user["id"],
                project_id=project_id,
                existing_todos=existing_todos,
            ):
                if ev.get("type") in ("tool_start", "tool_result", "command_started", "command_result", "file_changed", "approval_required", "todo_update"):
                    await agent_store.append_tool_event(user["id"], session_id, ev)
                if ev.get("type") == "todo_update" and ev.get("todos"):
                    await agent_store.update_agent_todos(user["id"], session_id, ev["todos"])
                if ev.get("type") == "file_changed" and ev.get("path"):
                    if ev["path"] not in changed:
                        changed.append(ev["path"])
                if ev.get("type") == "approval_required":
                    await agent_store.update_pending_approval(user["id"], session_id, ev)
                if ev.get("type") == "error":
                    had_error = True
                    error_msg = ev.get("message", "")
                if ev.get("type") == "completed" and ev.get("content"):
                    full_assistant.append(ev["content"])
                yield json.dumps(ev) + "\n"
        except Exception as e:
            had_error = True
            error_msg = str(e)[:500]
            yield json.dumps({"type": "error", "message": error_msg}) + "\n"
        finally:
            if full_assistant:
                txt = "\n".join(full_assistant)
                await agent_store.append_agent_message(user["id"], session_id, "assistant", txt[:10000])
                if changed:
                    await agent_store.mark_changed_files(user["id"], session_id, changed)
                await agent_store.update_agent_status(user["id"], session_id, "completed")
            elif had_error:
                await agent_store.update_agent_status(user["id"], session_id, "error")
                if "ALL_MODELS_EXHAUSTED" in error_msg:
                    await agent_store.append_tool_event(user["id"], session_id, {"type": "error", "message": error_msg})
            yield json.dumps({"type": "session_ended", "sessionId": session_id, "changedFiles": changed}) + "\n"

    return StreamingResponse(event_generator(), media_type="application/x-ndjson", headers={"X-Agent-Session-Id": session_id})


@router.post("/sessions/{session_id}/build")
async def build_from_plan(session_id: str, user: dict = Depends(get_current_user)):
    """Approve a Plan session and start Build using its todos (Phase 2)."""
    doc = await agent_store.get_agent_session(user["id"], session_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Agent session not found.")
    todos = doc.get("todos") or []
    if not todos:
        raise HTTPException(status_code=400, detail="No plan todos to build from — run Plan mode first.")
    project_id = str(doc.get("projectId")) if doc.get("projectId") else None
    if not project_id:
        raise HTTPException(status_code=400, detail="Session has no project.")
    pdoc = await project_model.get_project(user["id"], project_id)
    if pdoc is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    workspace = get_project_workspace(user["id"], project_id)
    workspace.mkdir(parents=True, exist_ok=True)
    project_info = {"name": pdoc.get("name", ""), "description": pdoc.get("description", ""), "template": pdoc.get("template", ""), "stack": pdoc.get("stack", ""), "workspace": str(workspace)}
    await project_model.touch_project(user["id"], project_id)
    history = doc.get("messages", [])
    # Update mode to build
    await agent_store.update_agent_status(user["id"], session_id, "active")
    # Store mode change via direct DB
    try:
        from app.db import get_db
        from app.models.agent_session import _safe_oid
        oid = _safe_oid(session_id)
        uid = _safe_oid(user["id"])
        if oid and uid:
            await get_db().agent_sessions.update_one({"_id": oid, "userId": uid}, {"$set": {"mode": "build"}})
    except Exception:
        pass

    async def event_generator():
        yield json.dumps({"type": "session_started", "sessionId": session_id, "mode": "build", "title": doc.get("title", "Agent Session"), "projectId": project_id}) + "\n"
        yield json.dumps({"type": "project_loaded", "projectId": project_id, "project": project_info}) + "\n"
        full_assistant = []
        changed: list[str] = []
        had_error = False
        error_msg = ""
        try:
            async for ev in stream_agent_loop(
                user_message=f"Approved plan with {len(todos)} steps — execute it now.",
                mode="build",
                model=None,
                history=history,
                workspace=workspace,
                project_info=project_info,
                user_id=user["id"],
                project_id=project_id,
                existing_todos=todos,
            ):
                if ev.get("type") in ("tool_start", "tool_result", "command_started", "command_result", "file_changed", "approval_required", "todo_update"):
                    await agent_store.append_tool_event(user["id"], session_id, ev)
                if ev.get("type") == "todo_update" and ev.get("todos"):
                    await agent_store.update_agent_todos(user["id"], session_id, ev["todos"])
                if ev.get("type") == "file_changed" and ev.get("path"):
                    if ev["path"] not in changed:
                        changed.append(ev["path"])
                if ev.get("type") == "approval_required":
                    await agent_store.update_pending_approval(user["id"], session_id, ev)
                if ev.get("type") == "error":
                    had_error = True
                    error_msg = ev.get("message", "")
                if ev.get("type") == "completed" and ev.get("content"):
                    full_assistant.append(ev["content"])
                yield json.dumps(ev) + "\n"
        except Exception as e:
            had_error = True
            error_msg = str(e)[:500]
            yield json.dumps({"type": "error", "message": error_msg}) + "\n"
        finally:
            if full_assistant:
                txt = "\n".join(full_assistant)
                await agent_store.append_agent_message(user["id"], session_id, "assistant", txt[:10000])
                if changed:
                    await agent_store.mark_changed_files(user["id"], session_id, changed)
                await agent_store.update_agent_status(user["id"], session_id, "completed")
            elif had_error:
                await agent_store.update_agent_status(user["id"], session_id, "error")
                if "ALL_MODELS_EXHAUSTED" in error_msg:
                    await agent_store.append_tool_event(user["id"], session_id, {"type": "error", "message": error_msg})
            yield json.dumps({"type": "session_ended", "sessionId": session_id, "changedFiles": changed}) + "\n"

    return StreamingResponse(event_generator(), media_type="application/x-ndjson", headers={"X-Agent-Session-Id": session_id})


@router.post("/stream")
async def agent_stream(req: AgentRequest, user: Optional[dict] = Depends(optional_current_user)):
    mode = req.mode if req.mode in ("plan", "build") else "build"

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
            await project_model.touch_project(user["id"], project_id)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Workspace error: {e}")
    elif project_id and user is None:
        try:
            workspace = get_project_workspace("guest", project_id)
            project_info = {"name": "Guest Project", "workspace": str(workspace), "stack": "", "template": ""}
        except Exception:
            workspace = None
    else:
        raise HTTPException(
            status_code=400,
            detail="No project selected. Select a project to start working.",
        )

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
            # For streaming, also pass existing todos if any
            existing_todos = doc.get("todos", [])
        else:
            existing_todos = []
    else:
        existing_todos = []

    async def event_generator():
        yield json.dumps({"type": "session_started", "sessionId": session_id, "mode": mode, "title": _short_title(req.message), "projectId": project_id}) + "\n"
        if project_info:
            yield json.dumps({"type": "project_loaded", "projectId": project_id, "project": project_info}) + "\n"
        full_assistant = []
        changed: list[str] = []
        had_error = False
        error_msg = ""
        try:
            async for ev in stream_agent_loop(
                user_message=req.message, mode=mode, model=req.model, history=history, workspace=workspace, project_info=project_info, user_id=uid if not is_guest else None, project_id=project_id, existing_todos=existing_todos
            ):
                if not is_guest and ev.get("type") in ("tool_start", "tool_result", "command_started", "command_result", "file_changed", "approval_required", "todo_update"):
                    await agent_store.append_tool_event(uid, session_id, ev)
                if ev.get("type") == "todo_update" and ev.get("todos"):
                    if not is_guest:
                        await agent_store.update_agent_todos(uid, session_id, ev["todos"])
                if ev.get("type") == "file_changed" and ev.get("path"):
                    if ev["path"] not in changed:
                        changed.append(ev["path"])
                if ev.get("type") == "approval_required":
                    if not is_guest:
                        await agent_store.update_pending_approval(uid, session_id, ev)
                if ev.get("type") == "error":
                    had_error = True
                    error_msg = ev.get("message", "")
                if ev.get("type") == "completed" and ev.get("content"):
                    full_assistant.append(ev["content"])
                yield json.dumps(ev) + "\n"
        except Exception as e:
            had_error = True
            error_msg = str(e)[:500]
            yield json.dumps({"type": "error", "message": error_msg}) + "\n"
        finally:
            if not is_guest:
                # Mark inspected after first run (helps /continue skip re-inspect)
                try:
                    await agent_store.set_inspected(uid, session_id, True)
                except Exception:
                    pass
                if full_assistant:
                    txt = "\n".join(full_assistant)
                    await agent_store.append_agent_message(uid, session_id, "assistant", txt[:10000])
                    if changed:
                        await agent_store.mark_changed_files(uid, session_id, changed)
                    await agent_store.update_agent_status(uid, session_id, "completed")
                elif had_error:
                    # Don't leave stuck in active — mark as error so Continue works
                    await agent_store.update_agent_status(uid, session_id, "error")
                    if "ALL_MODELS_EXHAUSTED" in error_msg:
                        # also surface a tool event for UI
                        await agent_store.append_tool_event(uid, session_id, {"type": "error", "message": error_msg})
            yield json.dumps({"type": "session_ended", "sessionId": session_id, "changedFiles": changed}) + "\n"

    return StreamingResponse(event_generator(), media_type="application/x-ndjson", headers={"X-Agent-Session-Id": session_id})
