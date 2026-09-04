"""Workspace filesystem management — per-project isolation, scaffolding, tree, stack detection."""
import os
import re
import shutil
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

from app.config import PROJECT_DIR

# Root for all project workspaces: <repo>/workspaces
WORKSPACES_ROOT: Path = (PROJECT_DIR / "workspaces").resolve()
WORKSPACES_ROOT.mkdir(parents=True, exist_ok=True)

IGNORE_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", "dist", "build", ".next", "coverage"}

TEMPLATE_SCAFFOLDS = {
    "react": {
        "package.json": """{
  "name": "{slug}",
  "private": true,
  "type": "module",
  "scripts": {"dev": "vite", "build": "vite build", "preview": "vite preview"},
  "dependencies": {"react": "^18.2.0", "react-dom": "^18.2.0"},
  "devDependencies": {"vite": "^5.0.0", "@vitejs/plugin-react": "^4.2.0"}
}
""",
        "vite.config.js": """import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({ plugins: [react()] });
""",
        "index.html": """<!DOCTYPE html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{name}</title></head><body><div id='root'></div><script type='module' src='/src/main.jsx'></script></body></html>""",
        "src/main.jsx": """import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.jsx';
createRoot(document.getElementById('root')).render(<App />);
""",
        "src/App.jsx": """export default function App() {
  return <div style={{padding:32,fontFamily:'system-ui'}}>
    <h1>{name}</h1>
    <p>Welcome to your React project. Ask Spike Agent to build features.</p>
  </div>;
}
""",
        "README.md": "# {name}\n\nReact + Vite project created by Spike Agent.\n\n```bash\nnpm install\nnpm run dev\n```\n",
    },
    "nextjs": {
        "package.json": """{
  "name": "{slug}",
  "private": true,
  "scripts": {"dev": "next dev", "build": "next build", "start": "next start"},
  "dependencies": {"next": "^14.0.0", "react": "^18.2.0", "react-dom": "^18.2.0"}
}
""",
        "next.config.js": """/** @type {import('next').NextConfig} */
const nextConfig = {};
module.exports = nextConfig;
""",
        "app/page.js": """export default function Page() {
  return <main style={{padding:32}}><h1>{name}</h1><p>Next.js project — ask Spike Agent to build.</p></main>;
}
""",
        "app/layout.js": """export default function Layout({children}) { return <html><body>{children}</body></html>; }
""",
        "README.md": "# {name}\n\nNext.js project.\n",
    },
    "node": {
        "package.json": """{
  "name": "{slug}",
  "version": "1.0.0",
  "type": "module",
  "scripts": {"dev": "node server/index.js", "start": "node server/index.js", "test": "node --test"},
  "dependencies": {"express": "^4.18.0"}
}
""",
        "server/index.js": """import express from 'express';
const app = express();
app.get('/', (req,res)=>res.send('<h1>{name}</h1><p>Node + Express — ask Spike Agent to build.</p>'));
app.listen(3000, ()=>console.log('Server on http://localhost:3000'));
""",
        "README.md": "# {name}\n\nNode.js + Express.\n",
    },
    "python": {
        "requirements.txt": "fastapi\nuvicorn\n",
        "main.py": """from fastapi import FastAPI
app = FastAPI()

@app.get("/")
def root():
    return {"message": "Hello from {name}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
""",
        "README.md": "# {name}\n\nPython project.\n\n```bash\npip install -r requirements.txt\npython main.py\n```\n",
    },
    "fastapi": {
        "requirements.txt": "fastapi\nuvicorn\nmotor\n",
        "main.py": """from fastapi import FastAPI
app = FastAPI(title="{name}")

@app.get("/")
def root():
    return {"message": "Hello from {name} — FastAPI"}

@app.get("/health")
def health():
    return {"status": "ok"}
""",
        "README.md": "# {name}\n\nFastAPI project.\n",
    },
    "html": {
        "index.html": """<!DOCTYPE html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'><title>{name}</title><link rel='stylesheet' href='style.css'></head><body><h1>{name}</h1><p>HTML/CSS/JS project — ask Spike Agent to build.</p><script src='script.js'></script></body></html>""",
        "style.css": "body{font-family:system-ui;padding:32px}h1{color:#6366f1}",
        "script.js": "console.log('{name} ready');",
        "README.md": "# {name}\n\nHTML/CSS/JS.\n",
    },
    "other": {
        "README.md": "# {name}\n\nProject created by Spike Agent.\n\nAsk the agent to build features.\n",
        ".gitignore": "node_modules/\n.venv/\n__pycache__/\ndist/\nbuild/\n.env\n",
    },
}


def is_local_workspace(workspace_str: str) -> bool:
    return str(workspace_str or "").startswith("local:")

def get_local_path(workspace_str: str) -> Optional[str]:
    if is_local_workspace(workspace_str):
        return str(workspace_str)[6:]
    return None

def get_workspace(user_id: str, project_id: str) -> Path:
    """Resolve workspace path for a project (ensures directory exists). For local projects, still returns server mirror path."""
    p = (WORKSPACES_ROOT / str(user_id) / str(project_id)).resolve()
    try:
        p.relative_to(WORKSPACES_ROOT)
    except ValueError:
        raise ValueError("Workspace escapes root")
    p.mkdir(parents=True, exist_ok=True)
    return p


def ensure_workspace(user_id: str, project_id: str) -> Path:
    return get_workspace(user_id, project_id)


def detect_stack(workspace: Path) -> str:
    """Detect stack from workspace files."""
    has = lambda p: (workspace / p).exists()
    stacks = []
    if has("package.json"):
        try:
            txt = (workspace / "package.json").read_text()[:2000]
            if "next" in txt.lower():
                stacks.append("Next.js")
            elif "vite" in txt.lower() or "react" in txt.lower():
                stacks.append("React")
            else:
                stacks.append("Node.js")
        except Exception:
            stacks.append("Node.js")
    if has("requirements.txt") or has("pyproject.toml") or has("Pipfile"):
        if has("main.py") and "fastapi" in (workspace / "main.py").read_text()[:1000].lower() if has("main.py") else False:
            stacks.append("FastAPI")
        else:
            stacks.append("Python")
    if has("vite.config.js") or has("vite.config.ts"):
        if "React" not in stacks:
            stacks.append("Vite")
    if has("index.html") and has("style.css"):
        stacks.append("HTML")
    if not stacks:
        # Only report "Empty" when the directory genuinely contains zero
        # usable files (ignoring dotfiles). Otherwise label it honestly.
        try:
            usable = [
                p for p in workspace.iterdir()
                if not p.name.startswith(".") and p.name not in IGNORE_DIRS
            ]
        except Exception:
            usable = []
        if not usable:
            stacks.append("Empty")
        elif (workspace / "src").exists():
            stacks.append("General (src/)")
        else:
            stacks.append("General")
    return " + ".join(stacks[:3])


def scaffold_project(workspace: Path, name: str, template: str):
    """Create scaffold files for a new project."""
    tmpl = (template or "other").lower()
    if tmpl not in TEMPLATE_SCAFFOLDS:
        tmpl = "other"
    files = TEMPLATE_SCAFFOLDS[tmpl]
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "project"
    for rel, content in files.items():
        dest = workspace / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            continue
        # Safe replacement — only {name} and {slug}, don't use str.format on arbitrary braces
        txt = content.replace("{name}", name).replace("{slug}", slug)
        dest.write_text(txt, encoding="utf-8")
    # Always ensure .gitignore and README
    if not (workspace / ".gitignore").exists():
        (workspace / ".gitignore").write_text(TEMPLATE_SCAFFOLDS["other"][".gitignore"], encoding="utf-8")


def build_file_tree(workspace: Path, max_depth: int = 3, max_entries: int = 200) -> List[Dict]:
    """Build a tree structure for explorer (limited depth)."""
    def walk(dir_path: Path, depth: int) -> List[Dict]:
        if depth > max_depth:
            return []
        entries = []
        try:
            for p in sorted(dir_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                if p.name in IGNORE_DIRS or p.name.startswith(".") and p.name not in (".gitignore",):
                    if p.name == ".git":
                        continue
                    if p.name in {".venv", "node_modules"}:
                        continue
                if p.name == ".env":
                    continue
                if len(entries) >= max_entries:
                    break
                if p.is_dir():
                    children = walk(p, depth + 1) if depth < max_depth else []
                    entries.append({"name": p.name, "path": p.relative_to(workspace).as_posix(), "type": "dir", "children": children})
                else:
                    try:
                        sz = p.stat().st_size
                    except Exception:
                        sz = 0
                    entries.append({"name": p.name, "path": p.relative_to(workspace).as_posix(), "type": "file", "size": sz})
        except Exception:
            pass
        return entries
    if not workspace.exists():
        return []
    return walk(workspace, 0)


def extract_zip_safely(zip_path: Path, workspace: Path, max_files: int = 500, max_size: int = 50 * 1024 * 1024):
    """Extract ZIP into workspace with traversal and bomb protection."""
    total = 0
    count = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            count += 1
            if count > max_files:
                raise ValueError("Too many files in archive")
            # Prevent traversal
            name = info.filename.replace("\\", "/").lstrip("/")
            if not name or name.startswith("__MACOSX") or ".." in name:
                continue
            # Prevent absolute paths
            if name.startswith("/"):
                continue
            dest = (workspace / name).resolve()
            try:
                dest.relative_to(workspace.resolve())
            except ValueError:
                continue
            total += info.file_size
            if total > max_size:
                raise ValueError("Archive too large")
            if info.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
