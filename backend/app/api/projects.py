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
    try:
        items = await proj_model.list_projects(user["id"], search or "")
    except Exception as e:
        import logging, traceback
        logging.getLogger("uvicorn.error").error(f"GET /api/projects failed: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=503, detail="Database temporarily unavailable.")
    out = []
    for doc in items:
        if str(doc.get("workspace", "")).startswith("local:"):
            # Local projects live on the user's PC; the server mirror dir
            # says nothing about their stack. Never overwrite with "Empty".
            doc["stack"] = doc.get("stack") or "Local"
            d = _to_out(doc)
            d["local"] = True
            out.append(d)
            continue
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
    if str(doc.get("workspace", "")).startswith("local:"):
        doc["stack"] = doc.get("stack") or "Local"
        d = _to_out(doc)
        d["local"] = True
        return d
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
    is_local = str(doc.get("workspace", "")).startswith("local:")
    if is_local:
        # Local projects: remove ONLY the Spike registration.
        # The actual folder on the user's PC must remain untouched.
        pass
    else:
        # Cloud workspace: remove the server-side workspace directory.
        ws = get_workspace(user["id"], project_id)
        try:
            if ws.exists():
                shutil.rmtree(ws, ignore_errors=True)
        except Exception:
            pass
    ok = await proj_model.delete_project(user["id"], project_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Project not found.")
    return {"status": "deleted", "local": is_local}


@router.get("/{project_id}/files")
async def list_files(project_id: str, path: str = Query(".", description="Relative path inside workspace"), user: dict = Depends(get_current_user)):
    doc = await proj_model.get_project(user["id"], project_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Project not found.")
    if str(doc.get("workspace", "")).startswith("local:"):
        try:
            from app.api.bridge import forward_tool_to_bridge
            res = await forward_tool_to_bridge(user["id"], project_id, "list_directory", {"path": path or "."}, timeout=10.0)
            if not res.get("success"):
                # If bridge offline, return offline status
                if "offline" in res.get("output", "").lower() or "not connected" in res.get("output", "").lower():
                    raise HTTPException(status_code=503, detail=res.get("output"))
                raise HTTPException(status_code=500, detail=res.get("output"))
            # Parse output: "# . (5 entries...)\nfile\n..."
            lines = res.get("output", "").split("\n")[1:]
            entries = []
            for line in lines:
                line=line.strip()
                if not line or line.startswith("#") or line.startswith("…"):
                    continue
                if line.endswith("/"):
                    name=line[:-1]
                    entries.append({"name": name, "path": (Path(path or ".") / name).as_posix() if path not in (".", "") else name, "type": "dir"})
                else:
                    name=line.split("  ")[0]
                    entries.append({"name": name, "path": (Path(path or ".") / name).as_posix() if path not in (".", "") else name, "type": "file", "size": 0})
            return {"path": path or ".", "entries": entries, "projectId": project_id, "local": True}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Local bridge unavailable: {e}")
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
        try:
            sz = target.stat().st_size
            return {"type": "file", "path": rel, "size": sz, "name": target.name}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
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
    # For local projects, forward to bridge
    if str(doc.get("workspace", "")).startswith("local:"):
        try:
            from app.api.bridge import forward_tool_to_bridge
            res = await forward_tool_to_bridge(user["id"], project_id, "inspect_project", {}, timeout=10.0)
            # For tree, we need to use list_directory or a dedicated tree tool
            # For now, try to get file tree via bridge's list_directory
            # We can call the bridge's file tree via a tool
            # As a fallback, return a placeholder that indicates it's local and needs bridge
            # We will try to use the bridge to list the directory
            tree_res = await forward_tool_to_bridge(user["id"], project_id, "list_directory", {"path": "."}, timeout=10.0)
            if tree_res.get("success"):
                # Parse the output which is like "# . (5 entries...)\nfile1\nfile2"
                # For now, return a simple tree based on that output
                # We should have a proper tree tool, but for now, return empty and let frontend handle
                # The frontend will show "Local project - connect bridge to see files"
                # We can try to build a simple tree from the output
                lines = tree_res.get("output", "").split("\n")[1:]  # Skip header
                entries = []
                for line in lines:
                    line=line.strip()
                    if not line or line.startswith("#") or line.startswith("…"):
                        continue
                    # line is like "src/" or "package.json  (123 bytes)"
                    if line.endswith("/"):
                        name=line[:-1]
                        entries.append({"name": name, "path": name, "type": "dir", "children": []})
                    else:
                        name=line.split("  ")[0]
                        entries.append({"name": name, "path": name, "type": "file", "size": 0})
                return {"projectId": project_id, "tree": entries, "stack": doc.get("stack", "Local"), "local": True}
            else:
                return {"projectId": project_id, "tree": [], "stack": doc.get("stack", "Local"), "local": True, "offline": True, "message": tree_res.get("output", "Bridge offline")}
        except Exception as e:
            return {"projectId": project_id, "tree": [], "stack": doc.get("stack", "Local"), "local": True, "offline": True, "error": str(e)}
    ws = get_workspace(user["id"], project_id)
    tree = build_file_tree(ws, max_depth=3)
    return {"projectId": project_id, "tree": tree, "stack": detect_stack(ws)}


@router.get("/{project_id}/file")
async def read_file(project_id: str, path: str = Query(..., description="Relative file path"), user: dict = Depends(get_current_user)):
    doc = await proj_model.get_project(user["id"], project_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Project not found.")
    if str(doc.get("workspace", "")).startswith("local:"):
        try:
            from app.api.bridge import forward_tool_to_bridge
            res = await forward_tool_to_bridge(user["id"], project_id, "read_file", {"path": path, "offset": 1, "limit": 400}, timeout=15.0)
            if not res.get("success"):
                if "offline" in res.get("output", "").lower():
                    raise HTTPException(status_code=503, detail=res.get("output"))
                raise HTTPException(status_code=404 if "not found" in res.get("output", "").lower() else 500, detail=res.get("output"))
            # Output is like "# path (lines...)\ncontent"
            out = res.get("output", "")
            # Strip header line
            if "\n" in out:
                content = out.split("\n", 1)[1]
            else:
                content = out
            return {"path": path.strip().replace("\\", "/").lstrip("/"), "content": content[:20000], "size": len(content), "local": True}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Local bridge unavailable: {e}")
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


@router.get("/{project_id}/git/status")
async def git_status(project_id: str, user: dict = Depends(get_current_user)):
    """Real git status for the project (branch + modified files). Read-only."""
    import subprocess
    doc = await proj_model.get_project(user["id"], project_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Project not found.")
    if str(doc.get("workspace", "")).startswith("local:"):
        try:
            from app.api.bridge import forward_tool_to_bridge
            res = await forward_tool_to_bridge(
                user["id"], project_id, "run_command",
                {"command": "git status --short --branch && echo --- && git log --oneline -5", "workdir": ".", "timeout": 15},
                timeout=20.0,
            )
            if not res.get("success") and "offline" in res.get("output", "").lower():
                raise HTTPException(status_code=503, detail=res.get("output"))
            return {"projectId": project_id, "local": True, "output": res.get("output", ""), "success": res.get("success", False)}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Local bridge unavailable: {e}")
    ws = get_workspace(user["id"], project_id)
    if not (ws / ".git").exists():
        return {"projectId": project_id, "local": False, "repo": False, "branch": None, "output": "Not a git repository."}
    try:
        branch = subprocess.run(["git", "branch", "--show-current"], cwd=str(ws), capture_output=True, text=True, timeout=10)
        st = subprocess.run(["git", "status", "--short", "--branch"], cwd=str(ws), capture_output=True, text=True, timeout=10)
        out = (st.stdout or st.stderr or "").strip()
        return {"projectId": project_id, "local": False, "repo": True, "branch": (branch.stdout or "").strip() or None, "output": out or "(clean)"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"git status failed: {e}")


@router.get("/{project_id}/git/diff")
async def git_diff(project_id: str, path: str = Query("", description="Optional single file to diff"), user: dict = Depends(get_current_user)):
    """Real git diff (never fabricated). Read-only."""
    import subprocess
    doc = await proj_model.get_project(user["id"], project_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Project not found.")
    rel = (path or "").strip().replace("\\", "/").lstrip("/")
    if ".." in rel.split("/"):
        raise HTTPException(status_code=400, detail="Invalid path.")
    if str(doc.get("workspace", "")).startswith("local:"):
        try:
            from app.api.bridge import forward_tool_to_bridge
            cmd = "git diff -- " + rel if rel else "git diff --stat && echo === && git diff | head -c 12000"
            res = await forward_tool_to_bridge(
                user["id"], project_id, "run_command",
                {"command": cmd, "workdir": ".", "timeout": 15},
                timeout=20.0,
            )
            if not res.get("success") and "offline" in res.get("output", "").lower():
                raise HTTPException(status_code=503, detail=res.get("output"))
            return {"projectId": project_id, "local": True, "output": res.get("output", ""), "success": res.get("success", False)}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Local bridge unavailable: {e}")
    ws = get_workspace(user["id"], project_id)
    if not (ws / ".git").exists():
        raise HTTPException(status_code=404, detail="Not a git repository.")
    try:
        args = ["git", "diff", "--", rel] if rel else ["git", "diff"]
        proc = subprocess.run(args, cwd=str(ws), capture_output=True, text=True, timeout=10)
        out = (proc.stdout or "")[:12000] or "(no changes)"
        return {"projectId": project_id, "local": False, "output": out}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"git diff failed: {e}")


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
