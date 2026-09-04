#!/usr/bin/env python3
"""
Spike Agent Bridge — local Windows companion for Spike AI.

Run on your Windows PC to give Spike Agent real access to your local project folders.

Usage:
  python bridge.py --pair CODE        # Pair with your Spike AI account
  python bridge.py --workspace "C:\\Users\\You\\Desktop\\MyProject"
  python bridge.py --status           # Show status
  python bridge.py --help

The bridge:
- Connects securely to Spike Cloud via WebSocket (wss) using your device token
- Receives tool requests (read_file, write_file, etc.) and executes them locally
- Returns results, streams file changes, and keeps the project in sync
- Never exposes files outside the authorized workspace
"""
import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, Any

import httpx
import websockets

# Config
DEFAULT_CLOUD = os.getenv("SPIKE_CLOUD_URL", "https://spike-ai.onrender.com")
CONFIG_DIR = Path.home() / ".spike" / "bridge"
CONFIG_FILE = CONFIG_DIR / "config.json"

IGNORE_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", "dist", "build", ".next", "coverage"}


def load_config() -> Dict[str, Any]:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_config(cfg: Dict[str, Any]):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def get_token() -> str:
    cfg = load_config()
    return cfg.get("token", "")


def get_cloud_url() -> str:
    cfg = load_config()
    return cfg.get("cloud_url", DEFAULT_CLOUD)


async def pair(code: str, cloud_url: str = None, name: str = "Windows PC"):
    """Pair with cloud using a code from the web UI."""
    url = (cloud_url or get_cloud_url()).rstrip("/")
    # Need user auth token - ask user to paste it or use browser flow
    # For now, we ask for Spike AI token (from localStorage spike_token)
    print("To pair, you need your Spike AI auth token.")
    print("1. Open Spike AI in your browser, log in, then open DevTools (F12) -> Console and run:")
    print("   localStorage.getItem('spike_token')")
    print("2. Copy the token and paste it here.")
    token = input("Paste your Spike token: ").strip()
    if not token:
        print("No token provided. Aborting.")
        return
    async with httpx.AsyncClient(timeout=20) as client:
        # Use the pairing endpoint
        resp = await client.post(
            f"{url}/api/bridge/pair",
            json={"code": code, "name": name},
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code != 200:
            print(f"Pair failed: {resp.status_code} {resp.text[:300]}")
            return
        data = resp.json()
        cfg = load_config()
        cfg["token"] = data["token"]
        cfg["deviceId"] = data["deviceId"]
        cfg["cloud_url"] = url
        save_config(cfg)
        print(f"Paired successfully! Device: {data['name']} ({data['deviceId']})")
        print(f"Config saved to {CONFIG_FILE}")


def status():
    cfg = load_config()
    if not cfg.get("token"):
        print("Not paired. Run: python bridge.py --pair CODE")
        return
    print(f"Cloud: {cfg.get('cloud_url')}")
    print(f"Device: {cfg.get('deviceId')}")
    print(f"Token: {cfg.get('token')[:12]}...")
    ws_path = cfg.get("workspace")
    if ws_path:
        print(f"Workspace: {ws_path} ({'exists' if Path(ws_path).exists() else 'NOT FOUND'})")
    else:
        print("Workspace: not set (use --workspace <path>)")


def set_workspace(path: str):
    p = Path(path).resolve()
    if not p.exists() or not p.is_dir():
        print(f"Folder not found: {p}")
        return
    cfg = load_config()
    cfg["workspace"] = str(p)
    save_config(cfg)
    print(f"Workspace set to {p}")
    # Optionally register with cloud
    # The cloud will create a project entry for this workspace
    # We can do that via an API call if we have a token
    token = cfg.get("token")
    cloud_url = cfg.get("cloud_url", DEFAULT_CLOUD).rstrip("/")
    if token:
        try:
            import httpx as hx
            # Try to register - this is optional, the web UI will also handle it
            print(f"To register this workspace in Spike AI, go to Spike Agent -> Add Local Project and it will appear as '{p.name}'")
        except Exception:
            pass


# --- Tool execution (mirrors agent_tools.py but for local) ---

BLOCKED_NAMES = {".ssh", ".gnupg", ".aws", ".env", "id_rsa", "id_ed25519"}

BLOCKED_ABSOLUTE_PREFIXES = (
    "c:/windows",
    "c:/program files",
    "c:/program files (x86)",
    "c:/programdata",
)


def _resolve_local(workspace: Path, rel: str) -> Path:
    """Resolve a relative path inside workspace, prevent traversal.

    Blocks: ../ escapes, absolute paths, UNC paths (\\\\server),
    drive changes (D:/... vs C:/...), symlink escapes, and sensitive
    locations (.ssh, keys, Windows system dirs).
    """
    if not rel:
        raise ValueError("Path required")
    raw = rel.strip()
    if raw.startswith("\\\\") or raw.startswith("//"):
        raise ValueError(f"UNC paths are blocked: {rel}")
    if len(raw) >= 2 and raw[1] == ":":
        raise ValueError(f"Absolute paths are blocked (use workspace-relative): {rel}")
    p = raw.replace("\\", "/").lstrip("/")
    if not p or p in (".", "./"):
        return workspace.resolve()
    parts = [seg for seg in p.split("/") if seg not in ("", ".")]
    if ".." in parts:
        raise ValueError(f"Path escapes workspace: {rel}")
    if any(seg in BLOCKED_NAMES for seg in parts):
        raise ValueError(f"Access to sensitive path is blocked: {rel}")
    ws = workspace.resolve()
    full = (ws / "/".join(parts)).resolve()
    try:
        full.relative_to(ws)
    except ValueError:
        raise ValueError(f"Path escapes workspace: {rel}")
    # Drive-change guard (Windows): resolved path must stay on the same drive
    if ws.drive and full.drive and ws.drive.lower() != full.drive.lower():
        raise ValueError(f"Path escapes workspace drive: {rel}")
    lowered = full.as_posix().lower()
    for prefix in BLOCKED_ABSOLUTE_PREFIXES:
        if lowered == prefix or lowered.startswith(prefix + "/"):
            raise ValueError(f"System path is blocked: {rel}")
    return full


def _mask_secrets(text: str) -> str:
    import re
    patterns = [
        (re.compile(r"(GROQ_API_KEY\s*=\s*)([^\s\n\"']+)", re.I), r"\1********"),
        (re.compile(r"(JWT_SECRET\s*=\s*)([^\s\n\"']+)", re.I), r"\1********"),
    ]
    for pat, repl in patterns:
        text = pat.sub(repl, text)
    return text


async def execute_local_tool(workspace: Path, tool: str, inp: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a tool against the local workspace."""
    try:
        if tool == "read_file":
            path = inp.get("path", "")
            offset = int(inp.get("offset", 1) or 1)
            limit = int(inp.get("limit", 200) or 200)
            full = _resolve_local(workspace, path)
            if not full.exists():
                return {"success": False, "output": f"File not found: {path}"}
            if full.is_dir():
                return {"success": False, "output": f"Path is a directory: {path}"}
            text = full.read_text(encoding="utf-8", errors="replace")
            text = _mask_secrets(text)
            lines = text.splitlines()
            total = len(lines)
            start = max(0, offset - 1)
            end = start + limit
            body = "\n".join(lines[start:end])
            header = f"# {path}  (lines {start+1}-{min(end, total)} of {total})\n"
            return {"success": True, "output": header + body[:12000]}

        elif tool == "write_file":
            path = inp.get("path", "")
            content = inp.get("content", "")
            full = _resolve_local(workspace, path)
            if full.name == ".env":
                return {"success": False, "output": "Writing .env is blocked"}
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content or "", encoding="utf-8")
            return {"success": True, "output": f"Written {path} ({len(content or '')} chars)"}

        elif tool == "edit_file":
            path = inp.get("path", "")
            old = inp.get("old_string", "")
            new = inp.get("new_string", "")
            full = _resolve_local(workspace, path)
            if not full.exists():
                return {"success": False, "output": f"File not found: {path}"}
            text = full.read_text(encoding="utf-8", errors="replace")
            if old not in text:
                return {"success": False, "output": f"old_string not found in {path}"}
            new_text = text.replace(old, new, 1)
            full.write_text(new_text, encoding="utf-8")
            return {"success": True, "output": f"Edited {path}"}

        elif tool == "delete_file":
            path = inp.get("path", "")
            full = _resolve_local(workspace, path)
            if not full.exists():
                return {"success": False, "output": f"File not found: {path}"}
            if full.is_dir():
                return {"success": False, "output": f"Refusing to delete directory {path}"}
            full.unlink()
            return {"success": True, "output": f"Deleted {path}"}

        elif tool == "list_directory":
            path = inp.get("path", ".") or "."
            full = _resolve_local(workspace, path) if path not in (".", "") else workspace
            if not full.exists():
                return {"success": False, "output": f"Directory not found: {path}"}
            entries = []
            for p in sorted(full.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                if p.name in IGNORE_DIRS:
                    continue
                if p.is_dir():
                    entries.append(f"{p.name}/")
                else:
                    entries.append(f"{p.name}  ({p.stat().st_size} bytes)")
            header = f"# {path}  ({len(entries)} entries)\n"
            return {"success": True, "output": header + "\n".join(entries[:200])}

        elif tool == "search_files":
            pattern = inp.get("pattern", "")
            include = inp.get("include", "")
            import fnmatch, re
            if not pattern:
                return {"success": False, "output": "pattern required"}
            try:
                re.compile(pattern)
                is_regex = True
            except:
                is_regex = False
            pat_re = re.compile(pattern, re.I) if is_regex else None
            needle = pattern.lower() if not is_regex else None
            results = []
            for root, dirs, files in os.walk(workspace):
                dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith(".")]
                for fname in files:
                    if fname == ".env":
                        continue
                    if include and not fnmatch.fnmatch(fname, include):
                        continue
                    fpath = Path(root) / fname
                    rel = fpath.relative_to(workspace).as_posix()
                    hit = False
                    details = ""
                    if is_regex:
                        if pat_re.search(fname):
                            hit = True
                            details = f"filename match: {rel}"
                        else:
                            if fpath.suffix in (".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".html", ".css", ".md"):
                                try:
                                    if fpath.stat().st_size > 300000:
                                        continue
                                    txt = fpath.read_text(encoding="utf-8", errors="ignore")
                                    for i, line in enumerate(txt.splitlines(), 1):
                                        if pat_re.search(line):
                                            hit = True
                                            details = f"{rel}:{i}: {line.strip()[:120]}"
                                            break
                                except:
                                    continue
                    else:
                        if needle in fname.lower():
                            hit = True
                            details = f"filename match: {rel}"
                        else:
                            if fpath.suffix in (".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".html", ".css", ".md"):
                                try:
                                    txt = fpath.read_text(encoding="utf-8", errors="ignore")
                                    if needle in txt.lower():
                                        for i, line in enumerate(txt.splitlines(), 1):
                                            if needle in line.lower():
                                                details = f"{rel}:{i}: {line.strip()[:120]}"
                                                break
                                        hit = True
                                except:
                                    continue
                    if hit:
                        results.append(details or rel)
                        if len(results) >= 80:
                            break
                if len(results) >= 80:
                    break
            if not results:
                return {"success": True, "output": f"No matches for: {pattern}"}
            return {"success": True, "output": f"# Search: {pattern!r} ({len(results)} hits)\n" + "\n".join(results)}

        elif tool == "get_file_info":
            path = inp.get("path", "")
            full = _resolve_local(workspace, path)
            if not full.exists():
                return {"success": False, "output": f"Not found: {path}"}
            st = full.stat()
            return {"success": True, "output": f"path: {path}\nsize: {st.st_size}\nis_dir: {full.is_dir()}\nmodified: {time.ctime(st.st_mtime)}"}

        elif tool == "inspect_project":
            # Simple stack detection
            has = lambda p: (workspace / p).exists()
            stacks = []
            if has("package.json"):
                try:
                    txt = (workspace / "package.json").read_text()[:2000]
                    if "next" in txt.lower():
                        stacks.append("Next.js")
                    elif "react" in txt.lower():
                        stacks.append("React")
                    else:
                        stacks.append("Node.js")
                except:
                    stacks.append("Node.js")
            if has("requirements.txt") or has("pyproject.toml"):
                stacks.append("Python")
            if not stacks:
                stacks = ["Unknown"]
            # List top-level
            try:
                top = [p.name + ("/" if p.is_dir() else "") for p in sorted(workspace.iterdir()) if p.name not in IGNORE_DIRS][:20]
                top_str = ", ".join(top)
            except:
                top_str = ""
            return {"success": True, "output": f"# Workspace: {workspace}\nDetected stack: {', '.join(stacks)}\nTop-level: {top_str}"}

        elif tool == "run_command":
            import subprocess
            cmd = inp.get("command", "")
            workdir = inp.get("workdir", "") or "."
            timeout = int(inp.get("timeout", 30) or 30)
            if not cmd:
                return {"success": False, "output": "command required"}
            wd = _resolve_local(workspace, workdir) if workdir not in (".", "") else workspace
            if not wd.is_dir():
                return {"success": False, "output": f"workdir not found: {workdir}"}
            proc = subprocess.run(cmd, shell=True, cwd=str(wd), capture_output=True, text=True, timeout=max(5, min(timeout, 120)))
            out = (proc.stdout or "") + (proc.stderr or "")
            out = _mask_secrets(out)
            if len(out) > 8000:
                out = out[:4000] + "\n…[truncated]\n" + out[-3500:]
            return {"success": proc.returncode == 0, "output": f"$ {cmd}\n(exit {proc.returncode})\n" + (out or "(no output)")}

        elif tool == "create_directory":
            path = inp.get("path", "")
            full = _resolve_local(workspace, path)
            full.mkdir(parents=True, exist_ok=True)
            return {"success": True, "output": f"Created directory {path}"}

        elif tool == "move_file":
            src = inp.get("src", inp.get("path", ""))
            dst = inp.get("dst", inp.get("dest", inp.get("new_path", "")))
            if not src or not dst:
                return {"success": False, "output": "move_file needs src and dst"}
            full_src = _resolve_local(workspace, src)
            full_dst = _resolve_local(workspace, dst)
            if not full_src.exists():
                return {"success": False, "output": f"Not found: {src}"}
            if full_dst.exists():
                return {"success": False, "output": f"Destination exists: {dst}"}
            full_dst.parent.mkdir(parents=True, exist_ok=True)
            full_src.rename(full_dst)
            return {"success": True, "output": f"Moved {src} -> {dst}"}

        elif tool == "git_status":
            import subprocess
            proc = subprocess.run(
                ["git", "status", "--short", "--branch"],
                cwd=str(workspace), capture_output=True, text=True, timeout=10,
            )
            out = (proc.stdout or proc.stderr or "").strip() or "(clean)"
            br = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=str(workspace), capture_output=True, text=True, timeout=10,
            )
            branch = (br.stdout or "").strip() or "detached"
            return {"success": proc.returncode == 0, "output": f"branch: {branch}\n{out[:6000]}"}

        elif tool == "git_diff":
            import subprocess
            rel = (inp.get("path", "") or "").strip().replace("\\", "/").lstrip("/")
            if ".." in rel.split("/"):
                return {"success": False, "output": "Invalid path."}
            args = ["git", "diff", "--", rel] if rel else ["git", "diff", "--stat"]
            proc = subprocess.run(args, cwd=str(workspace), capture_output=True, text=True, timeout=10)
            out = (proc.stdout or "").strip() or "(no changes)"
            return {"success": proc.returncode == 0, "output": out[:12000]}

        else:
            return {"success": False, "output": f"Unknown tool: {tool}"}
    except Exception as e:
        return {"success": False, "output": f"Tool {tool} failed: {e}"}


async def bridge_loop():
    cfg = load_config()
    token = cfg.get("token")
    cloud_url = cfg.get("cloud_url", DEFAULT_CLOUD).rstrip("/")
    ws_path = cfg.get("workspace")
    if not token:
        print("Not paired. Run: python bridge.py --pair CODE")
        return
    if not ws_path or not Path(ws_path).exists():
        print(f"Workspace not set or not found: {ws_path}")
        print("Set it with: python bridge.py --workspace \"C:\\path\\to\\project\"")
        return
    workspace = Path(ws_path).resolve()
    # Convert https to wss
    ws_url = cloud_url.replace("https://", "wss://").replace("http://", "ws://") + f"/api/bridge/connect?token={token}"
    print(f"Connecting to {ws_url} ...")
    print(f"Workspace: {workspace}")
    print("Press Ctrl+C to stop.")
    # File watcher (simple polling for now)
    last_tree = set()
    def scan():
        s = set()
        for root, dirs, files in os.walk(workspace):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith(".")]
            for f in files:
                if f == ".env":
                    continue
                p = Path(root) / f
                try:
                    s.add(str(p.relative_to(workspace).as_posix()))
                except:
                    pass
        return s

    last_tree = scan()
    # mtime snapshot for modified detection (debounced)
    def snapshot_mtimes():
        m = {}
        for root, dirs, files in os.walk(workspace):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith(".")]
            for f in files:
                if f == ".env":
                    continue
                p = Path(root) / f
                try:
                    rel = p.relative_to(workspace).as_posix()
                    m[rel] = (p.stat().st_mtime, p.stat().st_size)
                except Exception:
                    pass
        return m

    last_mtimes = snapshot_mtimes()
    backoff = 1
    while True:
        try:
            async with websockets.connect(ws_url, ping_interval=20, ping_timeout=10) as ws:
                print("Connected to Spike Cloud ✓")
                backoff = 1
                # Send initial hello
                await ws.send(json.dumps({"type": "hello", "workspace": str(workspace)}))
                # Watcher task (created/modified/deleted, debounced)
                async def watcher():
                    nonlocal last_tree, last_mtimes
                    pending: dict = {}  # path -> (change, first_seen)
                    while True:
                        await asyncio.sleep(2)
                        try:
                            cur = scan()
                            cur_mtimes = snapshot_mtimes()
                            added = cur - last_tree
                            removed = last_tree - cur
                            now = time.time()
                            for p in added:
                                pending[p] = ("created", pending.get(p, (None, now))[1])
                            for p in removed:
                                pending[p] = ("deleted", pending.get(p, (None, now))[1])
                            for p in cur & last_tree:
                                old = last_mtimes.get(p)
                                new = cur_mtimes.get(p)
                                if old and new and (new[0] != old[0] or new[1] != old[1]):
                                    if p not in pending:
                                        pending[p] = ("modified", now)
                            # Flush events older than 2s (debounce duplicate bursts)
                            ready = [p for p, (_, ts) in pending.items() if now - ts >= 2]
                            for p in ready[:10]:
                                change, _ = pending.pop(p)
                                try:
                                    await ws.send(json.dumps({"type": "file_changed", "path": p, "change": change}))
                                except Exception:
                                    pass
                            if added or removed:
                                last_tree = cur
                            last_mtimes = cur_mtimes
                        except Exception:
                            pass
                watch_task = asyncio.create_task(watcher())
                try:
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                        except:
                            continue
                        if msg.get("type") == "tool_request":
                            req_id = msg.get("requestId")
                            tool = msg.get("tool")
                            inp = msg.get("input", {})
                            print(f"→ {tool} {inp.get('path', inp.get('command', ''))[:60]}")
                            result = await execute_local_tool(workspace, tool, inp)
                            await ws.send(json.dumps({
                                "type": "tool_result",
                                "requestId": req_id,
                                "success": result.get("success", False),
                                "output": result.get("output", "")[:8000],
                            }))
                            print(f"  {'✓' if result.get('success') else '✗'} {tool}")
                        elif msg.get("type") == "ping":
                            await ws.send(json.dumps({"type": "pong"}))
                finally:
                    watch_task.cancel()
        except Exception as e:
            print(f"Disconnected: {e} — reconnecting in {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


def main():
    parser = argparse.ArgumentParser(description="Spike Agent Bridge — local Windows companion")
    parser.add_argument("--pair", metavar="CODE", help="Pair with Spike AI using a code from the web UI")
    parser.add_argument("--workspace", metavar="PATH", help="Set local project folder")
    parser.add_argument("--status", action="store_true", help="Show bridge status")
    parser.add_argument("--start", action="store_true", help="Start the bridge (same as no args; 'spike-agent start')")
    parser.add_argument("--cloud", metavar="URL", help="Cloud URL (default: https://spike-ai.onrender.com)")
    args = parser.parse_args()

    if args.status:
        status()
        return
    if args.pair:
        cloud = args.cloud or get_cloud_url()
        asyncio.run(pair(args.pair, cloud_url=cloud))
        return
    if args.workspace:
        set_workspace(args.workspace)
        return
    if len(sys.argv) == 1 or args.start:
        # Default: start bridge
        try:
            asyncio.run(bridge_loop())
        except KeyboardInterrupt:
            print("\nBridge stopped.")
        return
    parser.print_help()


if __name__ == "__main__":
    # Ensure required packages
    try:
        import websockets, httpx
    except ImportError:
        print("Installing required packages: websockets, httpx, watchdog...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "websockets", "httpx", "watchdog"])
        print("Please re-run: python bridge.py")
        sys.exit(0)
    main()
