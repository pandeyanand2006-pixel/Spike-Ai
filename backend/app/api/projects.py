"""Project workspace API."""
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File

from app.middleware.auth import get_current_user
from app.models import project as proj_model
from app.schemas.project import ProjectCreate, ProjectUpdate
from app.services.workspace_service import (
    WORKSPACES_ROOT,
    build_file_tree,
    detect_stack,
    extract_zip_safely,
    get_workspace,
    scaffold_project,
)

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _to_out(doc: dict) -> dict:
    return {
        "id": doc["id"],
        "name": doc.get("name", ""),
        "description": doc.get("description", ""),
        "template": doc.get("template", "other"),
        "stack": doc.get("stack", ""),
        "workspace": doc.get("workspace", ""),
        "createdAt": doc.get("createdAt", ""),
        "updatedAt": doc.get("updatedAt", ""),
        "lastOpenedAt": doc.get("lastOpenedAt", ""),
        "status": doc.get("status", "ready"),
    }


@router.post("", status_code=201)
async def create_project(req: ProjectCreate, user: dict = Depends(get_current_user)):
    # Create DB record first to get ID
    # Workspace path derived from userId/projectId
    # We need to insert then create dir; but we can generate workspace after
    # Use a temp to get ID: create doc with placeholder, then update workspace path
    from bson import ObjectId
    from app.db import get_db
    now_doc = await proj_model.create_project(user["id"], req.name, req.description or "", req.template or "other", "", "")
    pid = now_doc["id"]
    ws = get_workspace(user["id"], pid)
    # Scaffold
    try:
        scaffold_project(ws, req.name, req.template or "other")
        stack = detect_stack(ws)
    except Exception as e:
        stack = req.template or "other"
    # Update doc with workspace and stack
    await proj_model.update_project(user["id"], pid, {"workspace": str(ws), "stack": stack})
    doc = await proj_model.get_project(user["id"], pid)
    return _to_out(doc)


@router.get("")
async def list_projects(search: Optional[str] = Query(None), user: dict = Depends(get_current_user)):
    items = await proj_model.list_projects(user["id"], search or "")
    # Refresh stack detection lazily
    out = []
    for doc in items:
        # Ensure stack is current (in case files changed)
        try:
            ws = get_workspace(user["id"], doc["id"])
            doc["stack"] = detect_stack(ws) if ws.exists() else doc.get("stack", "")
        except Exception:
            pass
        out.append(_to_out(doc))
    return out


@router.get("/{project_id}")
async def get_project(project_id: str, user: dict = Depends(get_current_user)):
    doc = await proj_model.get_project(user["id"], project_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Project not found.")
    await proj_model.touch_project(user["id"], project_id)
    # Ensure workspace exists
    ws = get_workspace(user["id"], project_id)
    ws.mkdir(parents=True, exist_ok=True)
    doc["stack"] = detect_stack(ws)
    return _to_out(doc)


@router.patch("/{project_id}")
async def update_project(project_id: str, req: ProjectUpdate, user: dict = Depends(get_current_user)):
    doc = await proj_model.get_project(user["id"], project_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Project not found.")
    fields = {}
    if req.name is not None:
        fields["name"] = req.name.strip()[:80]
    if req.description is not None:
        fields["description"] = req.description[:300]
    if not fields:
        raise HTTPException(status_code=400, detail="Nothing to update.")
    await proj_model.update_project(user["id"], project_id, fields)
    doc = await proj_model.get_project(user["id"], project_id)
    return _to_out(doc)


@router.delete("/{project_id}")
async def delete_project(project_id: str, user: dict = Depends(get_current_user)):
    doc = await proj_model.get_project(user["id"], project_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Project not found.")
    # Remove workspace directory
    ws = get_workspace(user["id"], project_id)
    try:
        if ws.exists():
            shutil.rmtree(ws, ignore_errors=True)
    except Exception:
        pass
    ok = await proj_model.delete_project(user["id"], project_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Project not found.")
    return {"status": "deleted"}


@router.get("/{project_id}/files")
async def list_files(project_id: str, path: str = Query(".", description="Relative path inside workspace"), user: dict = Depends(get_current_user)):
    doc = await proj_model.get_project(user["id"], project_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Project not found.")
    ws = get_workspace(user["id"], project_id)
    rel = (path or ".").strip().replace("\\", "/").lstrip("/")
    if not rel or rel == ".":
        target = ws
    else:
        target = (ws / rel).resolve()
        try:
            target.relative_to(ws.resolve())
        except ValueError:
            raise HTTPException(status_code=400, detail="Path escapes workspace.")
    if not target.exists():
        raise HTTPException(status_code=404, detail="Path not found.")
    if target.is_file():
        # Return file info
        try:
            sz = target.stat().st_size
            return {"type": "file", "path": rel, "size": sz, "name": target.name}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    # Directory
    entries = []
    try:
        for p in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            if p.name in {".git", "__pycache__", ".venv", "venv", "node_modules"}:
                continue
            if p.is_dir():
                entries.append({"name": p.name, "path": (Path(rel) / p.name).as_posix() if rel != "." else p.name, "type": "dir"})
            else:
                try:
                    sz = p.stat().st_size
                except Exception:
                    sz = 0
                entries.append({"name": p.name, "path": (Path(rel) / p.name).as_posix() if rel != "." else p.name, "type": "file", "size": sz})
            if len(entries) > 300:
                break
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"path": rel, "entries": entries, "projectId": project_id}


@router.get("/{project_id}/tree")
async def get_tree(project_id: str, user: dict = Depends(get_current_user)):
    doc = await proj_model.get_project(user["id"], project_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Project not found.")
    ws = get_workspace(user["id"], project_id)
    tree = build_file_tree(ws, max_depth=3)
    return {"projectId": project_id, "tree": tree, "stack": detect_stack(ws)}


@router.get("/{project_id}/file")
async def read_file(project_id: str, path: str = Query(..., description="Relative file path"), user: dict = Depends(get_current_user)):
    doc = await proj_model.get_project(user["id"], project_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Project not found.")
    ws = get_workspace(user["id"], project_id)
    rel = path.strip().replace("\\", "/").lstrip("/")
    if not rel:
        raise HTTPException(status_code=400, detail="Path required.")
    target = (ws / rel).resolve()
    try:
        target.relative_to(ws.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Path escapes workspace.")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    if target.stat().st_size > 500_000:
        raise HTTPException(status_code=413, detail="File too large.")
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"path": rel, "content": text[:20000], "size": target.stat().st_size}


@router.post("/{project_id}/import")
async def import_project(project_id: str, file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    doc = await proj_model.get_project(user["id"], project_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Project not found.")
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip files are supported.")
    ws = get_workspace(user["id"], project_id)
    # Save temp zip
    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
        content = await file.read()
        if len(content) > 30 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="ZIP too large (max 30MB).")
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        extract_zip_safely(tmp_path, ws)
        stack = detect_stack(ws)
        await proj_model.update_project(user["id"], project_id, {"stack": stack})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import failed: {e}")
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
    return {"status": "imported", "stack": detect_stack(ws)}
