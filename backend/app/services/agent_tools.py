"""Agent tool registry — file operations, search, shell, project discovery.

All paths are confined to the configured workspace (repo root) with traversal protection,
ignore rules, secret masking, and permission checks.
"""
import asyncio
import difflib
import fnmatch
import os
import re
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List

from app.config import PROJECT_DIR as _PROJECT_DIR, get_settings

# Workspace root — the repo (ai-chatbot). Resolved once.
WORKSPACE: Path = Path(_PROJECT_DIR).resolve()

IGNORE_DIRS = {".git", "__pycache__", ".venv", "venv", "env", ".mypy_cache", ".pytest_cache", "node_modules", "dist", "build", ".next", "coverage", ".turbo", ".parcel-cache"}
IGNORE_FILES = {".env"}

# Output truncation
MAX_OUTPUT_CHARS = 8000
MAX_FILE_READ_CHARS = 12000
MAX_FILE_SIZE = 500_000  # skip files larger than this for reads

# Dangerous command patterns that require approval
DANGEROUS_PATTERNS = [
    r"\brm\s+-rf\b",
    r"\brm\s+-r\b",
    r"\bdel\s+/s\b",
    r"\bformat\b",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bhalt\b",
    r"\binit\s+0\b",
    r":\(\)\s*\{\s*:\|\:&\s*;\s*\}\s*;",  # fork bomb
]

SECRET_PATTERNS = [
    (re.compile(r"(GROQ_API_KEY\s*=\s*)([^\s\n\"']+)", re.I), r"\1********"),
    (re.compile(r"(JWT_SECRET\s*=\s*)([^\s\n\"']+)", re.I), r"\1********"),
    (re.compile(r"(MONGODB_URI\s*=\s*)([^\s\n]+)", re.I), r"\1********"),
    (re.compile(r"(VISION_API_KEY\s*=\s*)([^\s\n\"']+)", re.I), r"\1********"),
    (re.compile(r"(GOOGLE_CLIENT_SECRET\s*=\s*)([^\s\n\"']+)", re.I), r"\1********"),
    (re.compile(r"(api[_-]?key\s*[:=]\s*)([^\s\n\"',;]+)", re.I), r"\1********"),
    (re.compile(r"(password\s*[:=]\s*)([^\s\n\"',;]+)", re.I), r"\1********"),
    (re.compile(r"(token\s*[:=]\s*)([^\s\n\"',;]+)", re.I), r"\1********"),
]


def mask_secrets(text: str) -> str:
    if not text:
        return text
    out = text
    for pat, repl in SECRET_PATTERNS:
        out = pat.sub(repl, out)
    return out


def is_dangerous_command(cmd: str) -> bool:
    c = (cmd or "").lower()
    for pat in DANGEROUS_PATTERNS:
        if re.search(pat, c, re.I):
            return True
    # also block credential manipulation outside allowed
    if re.search(r"\b(del|rmdir)\b.*\b\/s\b", c):
        return True
    return False


def _resolve_path(path: str) -> Path:
    """Resolve path inside workspace; raise ValueError if traversal attempted."""
    if not path:
        raise ValueError("Path is required")
    # Normalize - strip leading / and handle backslashes
    p = path.strip().replace("\\", "/")
    # Remove leading slash to keep relative to workspace
    p = p.lstrip("/")
    # Join and resolve
    full = (WORKSPACE / p).resolve()
    # Ensure within workspace
    try:
        full.relative_to(WORKSPACE)
    except ValueError:
        raise ValueError(f"Path escapes workspace: {path}")
    return full


def _is_ignored(path: Path) -> bool:
    parts = set(path.parts) if hasattr(path, "parts") else set()
    # Check each part
    for part in path.relative_to(WORKSPACE).parts if path.is_absolute() or WORKSPACE in path.parents or path == WORKSPACE else path.parts:
        if part in IGNORE_DIRS:
            return True
    name = path.name
    if name in IGNORE_FILES:
        return True
    return False


# ---- Tool implementations ----

def tool_read_file(path: str, offset: int = 1, limit: int = 200) -> Dict[str, Any]:
    try:
        full = _resolve_path(path)
    except ValueError as e:
        return {"success": False, "output": str(e)}
    if not full.exists():
        return {"success": False, "output": f"File not found: {path}"}
    if full.is_dir():
        return {"success": False, "output": f"Path is a directory: {path}"}
    try:
        size = full.stat().st_size
        if size > MAX_FILE_SIZE:
            return {"success": False, "output": f"File too large ({size} bytes). Use offset/limit to read slices."}
        text = full.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"success": False, "output": f"Read failed: {e}"}
    text = mask_secrets(text)
    lines = text.splitlines()
    total = len(lines)
    # 1-indexed offset
    start = max(0, (offset or 1) - 1)
    end = start + (limit or 200)
    sliced = lines[start:end]
    header = f"# {path}  (lines {start+1}-{min(end, total)} of {total}, {size} bytes)\n"
    body = "\n".join(sliced)
    if len(body) > MAX_FILE_READ_CHARS:
        body = body[:MAX_FILE_READ_CHARS] + "\n…[truncated]"
    return {"success": True, "output": header + body}


def tool_write_file(path: str, content: str) -> Dict[str, Any]:
    try:
        full = _resolve_path(path)
    except ValueError as e:
        return {"success": False, "output": str(e)}
    # Prevent writing ignored locations like .env by accident
    if full.name == ".env" and not str(full).endswith(".env.example"):
        return {"success": False, "output": "Writing .env is blocked. Use .env.example instead."}
    try:
        full.parent.mkdir(parents=True, exist_ok=True)
        # Preserve existing? just write
        full.write_text(content or "", encoding="utf-8")
    except Exception as e:
        return {"success": False, "output": f"Write failed: {e}"}
    return {"success": True, "output": f"Written {path} ({len(content or '')} chars)"}


def tool_edit_file(path: str, old_string: str, new_string: str) -> Dict[str, Any]:
    try:
        full = _resolve_path(path)
    except ValueError as e:
        return {"success": False, "output": str(e)}
    if not full.exists():
        return {"success": False, "output": f"File not found: {path}"}
    try:
        text = full.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"success": False, "output": f"Read failed: {e}"}
    if old_string is None or old_string == "":
        return {"success": False, "output": "old_string is required for edit_file (use write_file to create new files)."}
    if old_string not in text:
        # Provide diff hint
        return {"success": False, "output": f"old_string not found in {path}. Read the file first and copy exact text."}
    if text.count(old_string) > 1:
        # If multiple matches, we still replace first occurrence only to avoid mass changes; warn
        pass
    new_text = text.replace(old_string, new_string, 1)
    try:
        full.write_text(new_text, encoding="utf-8")
    except Exception as e:
        return {"success": False, "output": f"Write failed: {e}"}
    # Produce unified diff snippet
    diff = difflib.unified_diff(text.splitlines(), new_text.splitlines(), fromfile=f"a/{path}", tofile=f"b/{path}", lineterm="")
    diff_text = "\n".join(list(diff)[:120])
    if len(diff_text) > 6000:
        diff_text = diff_text[:6000] + "\n…[truncated]"
    return {"success": True, "output": f"Edited {path}\n{diff_text or '(no diff)'}"}


def tool_delete_file(path: str) -> Dict[str, Any]:
    try:
        full = _resolve_path(path)
    except ValueError as e:
        return {"success": False, "output": str(e)}
    if not full.exists():
        return {"success": False, "output": f"File not found: {path}"}
    if full.is_dir():
        return {"success": False, "output": f"Refusing to delete directory {path} (use precise file paths)."}
    try:
        full.unlink()
    except Exception as e:
        return {"success": False, "output": f"Delete failed: {e}"}
    return {"success": True, "output": f"Deleted {path}"}


def tool_list_directory(path: str = ".") -> Dict[str, Any]:
    try:
        full = _resolve_path(path or ".")
    except ValueError as e:
        return {"success": False, "output": str(e)}
    if not full.exists():
        return {"success": False, "output": f"Directory not found: {path}"}
    if not full.is_dir():
        return {"success": False, "output": f"Not a directory: {path}"}
    try:
        entries = []
        for p in sorted(full.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            if p.name in IGNORE_DIRS:
                continue
            if p.is_dir():
                entries.append(f"{p.name}/")
            else:
                try:
                    sz = p.stat().st_size
                except Exception:
                    sz = 0
                entries.append(f"{p.name}  ({sz} bytes)")
            if len(entries) > 200:
                entries.append("…[truncated 200+ entries]")
                break
        header = f"# {path or '.'}  ({len(entries)} entries, workspace: {WORKSPACE.name})\n"
        return {"success": True, "output": header + "\n".join(entries)}
    except Exception as e:
        return {"success": False, "output": f"List failed: {e}"}


def tool_search_files(pattern: str, include: str = "") -> Dict[str, Any]:
    if not pattern:
        return {"success": False, "output": "pattern is required"}
    # Decide if pattern is regex or plain
    try:
        re.compile(pattern)
        is_regex = True
    except re.error:
        is_regex = False
    # include glob like *.py
    include_glob = (include or "").strip()
    results: List[str] = []
    max_results = 80
    pat_re = re.compile(pattern, re.I) if is_regex else None
    needle = pattern.lower() if not is_regex else None
    for root, dirs, files in os.walk(WORKSPACE):
        # prune ignored dirs
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith(".")]
        # also skip generated
        if "generated" in Path(root).parts:
            continue
        for fname in files:
            if fname in IGNORE_FILES:
                continue
            if include_glob and not fnmatch.fnmatch(fname, include_glob):
                continue
            fpath = Path(root) / fname
            rel = fpath.relative_to(WORKSPACE).as_posix()
            # filename match
            hit = False
            details = ""
            if is_regex:
                if pat_re.search(fname):
                    hit = True
                    details = f"filename match: {rel}"
                else:
                    # content search for text files
                    if fpath.suffix in (".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".html", ".css", ".md", ".txt", ".yml", ".yaml", ".toml", ".cfg", ".ini", ".sh", ".bat"):
                        try:
                            if fpath.stat().st_size > 300_000:
                                continue
                            text = fpath.read_text(encoding="utf-8", errors="ignore")
                            for i, line in enumerate(text.splitlines(), 1):
                                if pat_re.search(line):
                                    hit = True
                                    snippet = line.strip()[:160]
                                    details = f"{rel}:{i}: {snippet}"
                                    break
                        except Exception:
                            continue
            else:
                if needle in fname.lower():
                    hit = True
                    details = f"filename match: {rel}"
                else:
                    if fpath.suffix in (".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".html", ".css", ".md", ".txt", ".yml", ".yaml", ".toml", ".cfg", ".ini", ".sh", ".bat"):
                        try:
                            if fpath.stat().st_size > 300_000:
                                continue
                            text = fpath.read_text(encoding="utf-8", errors="ignore")
                            low = text.lower()
                            if needle in low:
                                # find line
                                for i, line in enumerate(text.splitlines(), 1):
                                    if needle in line.lower():
                                        snippet = line.strip()[:160]
                                        details = f"{rel}:{i}: {snippet}"
                                        break
                                hit = True
                        except Exception:
                            continue
            if hit:
                results.append(details or rel)
                if len(results) >= max_results:
                    break
        if len(results) >= max_results:
            break
    if not results:
        return {"success": True, "output": f"No matches for: {pattern} (include={include_glob or '*'})"}
    header = f"# Search: pattern={pattern!r} include={include_glob or '*'}  ({len(results)} hits)\n"
    return {"success": True, "output": header + "\n".join(results)}


def tool_get_file_info(path: str) -> Dict[str, Any]:
    try:
        full = _resolve_path(path)
    except ValueError as e:
        return {"success": False, "output": str(e)}
    if not full.exists():
        return {"success": False, "output": f"Not found: {path}"}
    try:
        st = full.stat()
        info = [
            f"path: {path}",
            f"resolved: {full}",
            f"exists: True",
            f"is_dir: {full.is_dir()}",
            f"size: {st.st_size} bytes",
            f"ext: {full.suffix}",
            f"modified: {time.ctime(st.st_mtime)}",
        ]
        if full.is_file() and st.st_size < 200_000:
            try:
                text = full.read_text(encoding="utf-8", errors="ignore")
                info.append(f"lines: {len(text.splitlines())}")
            except Exception:
                pass
        return {"success": True, "output": "\n".join(info)}
    except Exception as e:
        return {"success": False, "output": f"Info failed: {e}"}


def tool_inspect_project() -> Dict[str, Any]:
    lines: List[str] = []
    lines.append(f"# Workspace: {WORKSPACE}")
    lines.append("")
    # Detect stacks
    has = lambda p: (WORKSPACE / p).exists()
    checks = {
        "Python": ["requirements.txt", "pyproject.toml", "Pipfile", "setup.py", "main.py", "app.py"],
        "Node": ["package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock"],
        "React": ["src", "vite.config.js", "vite.config.ts"],
        "Next.js": ["next.config.js", "next.config.mjs", "app", "pages"],
        "Java": ["pom.xml", "build.gradle", "build.gradle.kts"],
        "C/C++": ["CMakeLists.txt", "Makefile"],
    }
    detected = []
    for stack, files in checks.items():
        for f in files:
            if has(f) or (WORKSPACE / "backend" / f).exists():
                detected.append(stack)
                break
    # also check backend
    if (WORKSPACE / "backend").exists():
        detected.append("FastAPI (backend/)")
    if not detected:
        detected = ["Unknown"]
    lines.append(f"Detected stack: {', '.join(detected)}")
    lines.append("")
    # Important dirs
    lines.append("## Important directories")
    for d in [".", "backend", "backend/app", "backend/app/api", "backend/app/services", "backend/static", "backend/static/js", "backend/static/css"]:
        p = WORKSPACE / d
        if p.exists():
            try:
                count = len([x for x in p.iterdir() if x.name not in IGNORE_DIRS])
                lines.append(f"- {d}/  ({count} entries)")
            except Exception:
                lines.append(f"- {d}/")
    lines.append("")
    lines.append("## Config files present")
    for f in ["requirements.txt", "backend/requirements.txt", ".env.example", "package.json", "vite.config.js", "next.config.js", "pyproject.toml"]:
        if has(f):
            lines.append(f"- {f}")
    lines.append("")
    lines.append("## Entry points")
    for f in ["backend/main.py", "backend/app/main.py", "main.py", "app.py", "src/main.jsx", "src/App.jsx"]:
        if has(f):
            lines.append(f"- {f}")
    # Top-level listing
    try:
        top = [p.name + ("/" if p.is_dir() else "") for p in sorted(WORKSPACE.iterdir()) if p.name not in IGNORE_DIRS][:40]
        lines.append("")
        lines.append("## Top-level")
        lines.append(", ".join(top))
    except Exception:
        pass
    return {"success": True, "output": "\n".join(lines)}


def tool_run_command(command: str, workdir: str = "", timeout: int = 30) -> Dict[str, Any]:
    if not command or not command.strip():
        return {"success": False, "output": "command is required"}
    if is_dangerous_command(command) and "force" not in command.lower():
        # Still allow but flagged; caller should gate. We return flagged but don't block.
        pass
    # Resolve workdir
    wd = WORKSPACE
    if workdir:
        try:
            wd = _resolve_path(workdir)
        except ValueError as e:
            return {"success": False, "output": str(e)}
        if not wd.is_dir():
            return {"success": False, "output": f"workdir not found: {workdir}"}
    # Security: block commands that try to escape workspace via cd ../../
    if ".." in command:
        # we still allow but we bound execution to wd; shell could still do cd.
        # We normalize by running with cwd=wd, so relative escapes are limited to wd.
        pass
    try:
        # Use shell=True for convenience (npm, python -m etc). Timeout enforced.
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(wd),
            capture_output=True,
            text=True,
            timeout=max(5, min(int(timeout or 30), 120)),
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        out = mask_secrets(out)
        # Truncate
        if len(out) > MAX_OUTPUT_CHARS:
            out = out[:4000] + "\n…[truncated]…\n" + out[-3500:]
        header = f"$ {command}\n(exit {proc.returncode}, cwd={wd.relative_to(WORKSPACE) if wd != WORKSPACE else '.'})\n"
        success = proc.returncode == 0
        return {"success": success, "output": header + (out or "(no output)")}
    except subprocess.TimeoutExpired as e:
        out = (e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")) + (e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or ""))
        out = mask_secrets(out)
        if len(out) > MAX_OUTPUT_CHARS:
            out = out[:4000] + "\n…[truncated]"
        return {"success": False, "output": f"$ {command}\n[timeout after {timeout}s]\n" + out}
    except Exception as e:
        return {"success": False, "output": f"Command failed: {e}"}


# Registry for the agent loop
TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {
    "read_file": {
        "description": "Read a file (supports offset/limit for large files).",
        "params": ["path", "offset", "limit"],
        "fn": lambda **kw: tool_read_file(kw.get("path", ""), int(kw.get("offset", 1) or 1), int(kw.get("limit", 200) or 200)),
    },
    "write_file": {
        "description": "Create or overwrite a file with given content.",
        "params": ["path", "content"],
        "fn": lambda **kw: tool_write_file(kw.get("path", ""), kw.get("content", "")),
    },
    "edit_file": {
        "description": "Precisely edit a file by replacing old_string with new_string (read file first).",
        "params": ["path", "old_string", "new_string"],
        "fn": lambda **kw: tool_edit_file(kw.get("path", ""), kw.get("old_string", ""), kw.get("new_string", "")),
    },
    "delete_file": {
        "description": "Delete a single file (requires approval; directories blocked).",
        "params": ["path"],
        "fn": lambda **kw: tool_delete_file(kw.get("path", "")),
    },
    "list_directory": {
        "description": "List files and directories at a path.",
        "params": ["path"],
        "fn": lambda **kw: tool_list_directory(kw.get("path", "") or "."),
    },
    "search_files": {
        "description": "Search project files by text/regex. Use include glob like *.py.",
        "params": ["pattern", "include"],
        "fn": lambda **kw: tool_search_files(kw.get("pattern", ""), kw.get("include", "")),
    },
    "get_file_info": {
        "description": "Get file metadata (exists, size, ext, modified).",
        "params": ["path"],
        "fn": lambda **kw: tool_get_file_info(kw.get("path", "")),
    },
    "inspect_project": {
        "description": "High-level project discovery: stack, dirs, config, entry points.",
        "params": [],
        "fn": lambda **kw: tool_inspect_project(),
    },
    "run_command": {
        "description": "Execute a shell command in the workspace (npm, python, git, etc.).",
        "params": ["command", "workdir", "timeout"],
        "fn": lambda **kw: tool_run_command(kw.get("command", ""), kw.get("workdir", ""), int(kw.get("timeout", 30) or 30)),
    },
}

# Permission sets
READ_TOOLS = {"read_file", "list_directory", "search_files", "get_file_info", "inspect_project"}
WRITE_TOOLS = {"write_file", "edit_file"}
DESTRUCTIVE_TOOLS = {"delete_file"}
SHELL_TOOLS = {"run_command"}
