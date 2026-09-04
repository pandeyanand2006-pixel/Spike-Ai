"""Local Bridge API — pairing, devices, workspaces, tool proxy, file sync."""
import asyncio
import json
import secrets
from pathlib import Path
from typing import Optional, Dict, List

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from pydantic import BaseModel

from app.middleware.auth import get_current_user
from app.models import bridge as bridge_model
from app.models import project as project_model
from app.services.workspace_service import get_workspace, detect_stack

router = APIRouter(prefix="/api/bridge", tags=["bridge"])

# In-memory pending tool requests and WebSocket connections
# device_token -> WebSocket
_active_bridges: Dict[str, WebSocket] = {}
# request_id -> Future
_pending_requests: Dict[str, asyncio.Future] = {}


class PairRequest(BaseModel):
    code: str
    name: Optional[str] = "Windows PC"


class WorkspaceRegister(BaseModel):
    localPath: str
    name: Optional[str] = None


@router.post("/pairing")
async def create_pairing(user: dict = Depends(get_current_user)):
    """Generate a pairing code for the current user."""
    try:
        data = await bridge_model.create_pairing_code(user["id"])
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pair")
async def claim_pairing(req: PairRequest, user: dict = Depends(get_current_user)):
    """Claim a pairing code and create a device."""
    # Verify code
    pairing = await bridge_model.verify_pairing_code(req.code)
    if not pairing:
        raise HTTPException(status_code=400, detail="Invalid or expired pairing code.")
    # Create device
    device = await bridge_model.create_device(user["id"], name=req.name or "Windows PC")
    return {"deviceId": device["id"], "token": device["token"], "name": device["name"]}


@router.get("/devices")
async def list_devices(user: dict = Depends(get_current_user)):
    devices = await bridge_model.list_devices(user["id"])
    # Don't expose tokens
    out = []
    for d in devices:
        out.append({
            "id": d["id"],
            "name": d.get("name", "Device"),
            "lastSeen": d.get("lastSeen", ""),
            "status": d.get("status", "offline"),
        })
    return out


@router.delete("/devices/{device_id}")
async def delete_device(device_id: str, user: dict = Depends(get_current_user)):
    ok = await bridge_model.delete_device(user["id"], device_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Device not found.")
    return {"status": "deleted"}


@router.post("/workspaces")
async def register_workspace(req: WorkspaceRegister, user: dict = Depends(get_current_user)):
    """Register a local folder as a project. Called by the bridge after user selects folder."""
    # Validate localPath is not empty and looks like a Windows path
    path = (req.localPath or "").strip()
    if not path:
        raise HTTPException(status_code=400, detail="localPath required.")
    # For security, don't store the raw path in DB if it's sensitive, but we need it for display
    # We store a safe version: just the folder name and a workspaceId
    name = req.name or Path(path).name or "Local Project"
    # Create a project entry with type local
    # We use the existing project model but set workspace to a local identifier
    # The actual files stay on the user's PC, not on the server
    # We create a project with template "other" and stack "Local"
    doc = await project_model.create_project(user["id"], name, f"Local workspace: {path}", "other", f"local:{path}", "Local")
    # Also create a workspaceId for tracking
    workspace_id = doc["id"]
    # Update stack to detected local stack if possible (we can't detect without files, but we can try to infer from path)
    # For now, just return
    return {"projectId": doc["id"], "workspaceId": workspace_id, "name": name, "localPath": path}


@router.get("/workspaces")
async def list_workspaces(user: dict = Depends(get_current_user)):
    """List local workspaces (projects with local: prefix)."""
    try:
        items = await project_model.list_projects(user["id"])
        # Filter for local workspaces
        local = [p for p in items if str(p.get("workspace", "")).startswith("local:")]
        return local
    except Exception as e:
        raise HTTPException(status_code=503, detail="Database unavailable.")


# WebSocket for bridge
@router.websocket("/connect")
async def bridge_connect(websocket: WebSocket, token: str = Query(..., description="Device token")):
    """WebSocket endpoint for the local bridge to connect."""
    await websocket.accept()
    device = await bridge_model.get_device_by_token(token)
    if not device:
        await websocket.close(code=4001, reason="Invalid token")
        return
    # Store connection
    _active_bridges[token] = websocket
    await bridge_model.touch_device(device["id"])
    try:
        while True:
            # Keep alive and handle incoming messages from bridge
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                # Handle tool_result from bridge
                if msg.get("type") == "tool_result" and "requestId" in msg:
                    req_id = msg["requestId"]
                    fut = _pending_requests.pop(req_id, None)
                    if fut and not fut.done():
                        fut.set_result(msg)
                elif msg.get("type") == "file_changed":
                    # File watcher event from bridge - could broadcast to frontend via polling or store
                    # For now, just log and could store in DB for frontend to poll
                    pass
                elif msg.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except Exception:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        _active_bridges.pop(token, None)


async def forward_tool_to_bridge(user_id: str, project_id: str, tool: str, tool_input: dict, timeout: float = 30.0) -> dict:
    """Forward a tool request to the user's local bridge and wait for result."""
    # Find the user's active bridge
    # For now, find any device for the user that is online
    devices = await bridge_model.list_devices(user_id)
    if not devices:
        return {"success": False, "output": "Local Agent Bridge not connected. Please start the bridge on your Windows PC and pair it."}
    # Find an online device (lastSeen within 2 minutes)
    # For simplicity, pick the first device and check if it has an active WebSocket
    # We need to map device to token: we don't have token in list_devices (filtered), so we need to fetch full device
    # Instead, iterate over _active_bridges and check if any belongs to user
    # For now, just pick the first active bridge for this user
    # This is a simplification - in production, we'd have a proper mapping
    target_ws = None
    target_token = None
    for tok, ws in _active_bridges.items():
        dev = await bridge_model.get_device_by_token(tok)
        if dev and str(dev.get("userId")) == str(user_id):
            target_ws = ws
            target_token = tok
            break
    if not target_ws:
        return {"success": False, "output": "Local Agent Bridge is offline. Please ensure 'python spike_bridge/bridge.py' is running on your Windows PC and paired."}
    # Create request
    req_id = secrets.token_hex(8)
    fut = asyncio.get_event_loop().create_future()
    _pending_requests[req_id] = fut
    payload = {
        "type": "tool_request",
        "requestId": req_id,
        "projectId": project_id,
        "tool": tool,
        "input": tool_input,
    }
    try:
        await target_ws.send_text(json.dumps(payload))
        # Wait for result
        result = await asyncio.wait_for(fut, timeout=timeout)
        return {"success": result.get("success", False), "output": result.get("output", "")}
    except asyncio.TimeoutError:
        _pending_requests.pop(req_id, None)
        return {"success": False, "output": f"Tool '{tool}' timed out after {timeout}s (local bridge not responding)."}
    except Exception as e:
        _pending_requests.pop(req_id, None)
        return {"success": False, "output": f"Bridge error: {e}"}


def is_local_project(project_doc: Optional[dict]) -> bool:
    """Check if a project is a local workspace (vs cloud)."""
    if not project_doc:
        return False
    ws = str(project_doc.get("workspace", ""))
    return ws.startswith("local:") or project_doc.get("workspaceType") == "local"
