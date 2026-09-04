"""Agent service — planning, tool loop, validation, and observability."""
import json
import re
import asyncio
from typing import Any, Dict, AsyncGenerator, List, Optional

from app.config import get_settings
from app.services.ai_service import ai_service
from pathlib import Path

from app.services.agent_tools import (
    TOOL_REGISTRY,
    READ_TOOLS,
    WRITE_TOOLS,
    DESTRUCTIVE_TOOLS,
    SHELL_TOOLS,
    WORKSPACE as DEFAULT_WORKSPACE,
    get_tool_registry,
    is_dangerous_command,
    mask_secrets,
)
from app.services.workspace_service import is_local_workspace

# ---------- System prompts ----------

AGENT_SYSTEM_PROMPT = """You are Spike Agent, an autonomous software engineering agent.

You work directly on the user's project workspace. You are NOT a chatbot — you must use tools to inspect and modify the project instead of only describing code.

Rules:
1. Understand the existing project before changing it. Prefer inspect_project, list_directory, read_file, search_files first.
2. Prefer minimal, targeted changes. Preserve existing functionality.
3. Never fabricate files, commands, test results, or tool outputs. Use tools instead of guessing.
4. Inspect relevant files before editing them.
5. Search the codebase when necessary.
6. For complex tasks, create an internal execution plan (explain steps, then execute).
7. Execute step by step. After changes, validate (run tests/build where relevant).
8. If validation fails, diagnose and fix.
9. Never claim success without verification.
10. Never expose secrets (.env, keys). Mask them.
11. Never perform destructive operations without required approval.
12. Stay inside the authorized workspace.
13. Do not reveal private chain-of-thought. Show concise action summaries.
14. Ask for clarification only when genuinely necessary; otherwise make reasonable assumptions and continue.
15. Finish the task completely whenever possible.

Tool calling format: You MUST respond with JSON when you want to use a tool. Use exactly one tool per turn:
{"tool": "<tool_name>", "input": { ... }}
Supported tools:
- read_file {path, offset, limit}
- write_file {path, content}
- edit_file {path, old_string, new_string}
- delete_file {path}
- list_directory {path}
- search_files {pattern, include}
- get_file_info {path}
- inspect_project {}
- run_command {command, workdir, timeout}

CRITICAL for write_file/edit_file: The "content" value MUST be a valid JSON string. Escape every double quote as \\" and every newline as \\n. Keep each file under 200 lines for this turn; for large websites, create the minimal viable version first, then expand in next steps. Example:
{"tool": "write_file", "input": {"path": "package.json", "content": "{\\n  \\"name\\": \\"chax\\",\\n  \\"version\\": \\"1.0.0\\"\\n}"}}

When you have completed the task, respond WITHOUT a tool call, with a concise summary including:
## Completed — what was done
### Changes — files created/edited
### Validation — tests/build results
### Next steps — if any
"""

PLAN_SUFFIX = """
MODE: PLAN — read-only. You may ONLY use: read_file, list_directory, search_files, get_file_info, inspect_project.
Do NOT attempt write_file, edit_file, delete_file, or run_command. Produce a clear implementation plan instead.
"""

BUILD_SUFFIX = """
MODE: BUILD — you may read, search, create, edit, run commands, test, and validate.
"""

TOOL_GUIDE = """
When you need to act, emit ONE JSON object per response: {"tool": "...", "input": {...}}.
Do not wrap it in markdown. Do not add extra text before the JSON.
If you are done, reply with plain markdown summary (no tool JSON).
"""

# Retry / loop limits
MAX_STEPS = 18
MAX_LLM_RETRIES = 2


def build_system_prompt(mode: str) -> str:
    base = AGENT_SYSTEM_PROMPT + "\n\n" + TOOL_GUIDE
    if mode == "plan":
        return base + "\n" + PLAN_SUFFIX
    return base + "\n" + BUILD_SUFFIX


def parse_tool_call(text: str) -> Optional[Dict[str, Any]]:
    """Extract a single tool call from LLM output. Expects JSON with tool+input."""
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.I)
    t = re.sub(r"\s*```$", "", t, flags=re.I).strip()
    try:
        obj = json.loads(t)
        if isinstance(obj, dict) and "tool" in obj and obj["tool"] in TOOL_REGISTRY:
            return {"tool": obj["tool"], "input": obj.get("input", {}) if isinstance(obj.get("input"), dict) else {}}
    except Exception:
        pass
    m = re.search(r"\{[^{}]*\"tool\"\s*:\s*\"[a-z_]+\"[^{}]*\}", t, re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict) and "tool" in obj and obj["tool"] in TOOL_REGISTRY:
                return {"tool": obj["tool"], "input": obj.get("input", {}) if isinstance(obj.get("input"), dict) else {}}
        except Exception:
            pass
    try:
        start = t.find("{")
        end = t.rfind("}")
        if start != -1 and end != -1 and end > start:
            obj = json.loads(t[start : end + 1])
            if isinstance(obj, dict) and "tool" in obj and obj["tool"] in TOOL_REGISTRY:
                return {"tool": obj["tool"], "input": obj.get("input", {}) if isinstance(obj.get("input"), dict) else {}}
    except Exception:
        pass
    return None


def is_likely_tool_call(text: str) -> bool:
    t = (text or "").strip()
    return '"tool"' in t and '"input"' in t and t.lstrip().startswith("{")

def try_fix_unescaped_write(text: str) -> Optional[Dict[str, Any]]:
    """Fallback for write_file where content has unescaped quotes/newlines."""
    try:
        m_path = re.search(r'"path"\s*:\s*"([^"]+)"', text)
        if not m_path:
            return None
        path = m_path.group(1)
        # Find content start
        m_start = re.search(r'"content"\s*:\s*"', text)
        if not m_start:
            return None
        start = m_start.end()
        # Try to find the closing of content: look for '",\s*}' or '"\s*}\s*}'
        # Use rfind for last occurrence of '"\n}' or '"}'
        remaining = text[start:]
        # Try to parse as JSON string by wrapping remaining and using json decoder with raw
        # Heuristic: find the last '}' that closes input, then outer '}'
        # For truncated, just take up to 3000 chars
        end = remaining.rfind('"}')
        if end == -1:
            end = remaining.rfind('" }')
        if end != -1:
            raw = remaining[:end]
        else:
            # Truncated — take up to next '}' or end
            raw = remaining[:3000]
            # Trim at last complete line
            if raw.count('"') % 2 == 1:
                raw = raw[: raw.rfind('"')]
        # Unescape: if raw contains literal \n, keep; if contains actual newlines, keep
        # Replace escaped sequences first
        try:
            content = raw.replace('\\n', '\n').replace('\\"', '"').replace('\\\\', '\\')
            # If content still looks JSON-like with unescaped quotes, keep as is
            return {"tool": "write_file", "input": {"path": path, "content": content}}
        except Exception:
            return None
    except Exception:
        return None
    return None


async def call_llm(messages: List[Dict[str, str]], model: Optional[str] = None) -> str:
    """Call Groq via the existing AIService (non-streaming) and return content."""
    settings = get_settings()
    mdl = model or settings.model
    try:
        resp = await ai_service.client.chat.completions.create(
            model=mdl,
            messages=messages,
            temperature=0.35,
            max_tokens=900,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        # Retry once with lower max_tokens on rate-limit
        msg = str(e)
        if "429" in msg or "rate_limit" in msg.lower() or "OTPM" in msg:
            try:
                resp = await ai_service.client.chat.completions.create(
                    model=mdl,
                    messages=messages[-6:],
                    temperature=0.35,
                    max_tokens=600,
                )
                return (resp.choices[0].message.content or "").strip()
            except Exception as e2:
                return f"LLM error: {e2}"
        return f"LLM error: {e}"


async def execute_tool(tool: str, inp: Dict[str, Any], mode: str, workspace: Path | None = None, project_info: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Execute a registered tool with permission checks (workspace-aware). For local projects, forward to bridge."""
    if mode == "plan" and tool not in READ_TOOLS:
        return {"success": False, "output": f"Tool '{tool}' is not allowed in Plan mode (read-only). Switch to Build to modify files/run commands."}
    if tool in DESTRUCTIVE_TOOLS and mode != "build":
        return {"success": False, "output": f"Tool '{tool}' requires Build mode."}
    # If this is a local project, forward to the local bridge
    is_local = False
    if project_info and is_local_workspace(project_info.get("workspace", "")):
        is_local = True
    elif workspace and is_local_workspace(str(workspace)):
        is_local = True
    if is_local:
        # Forward to local bridge
        try:
            from app.api.bridge import forward_tool_to_bridge
            # Need user_id and project_id from project_info
            # project_info should contain projectId, but we don't have it here directly
            # We can try to get it from workspace or project_info
            # For now, we need to handle this in stream_agent_loop where we have project_id
            # This fallback will be handled there
            pass
        except Exception:
            pass
        # If we are in local mode but no bridge forwarding is set up in this context, return offline message
        # The actual forwarding will be done in stream_agent_loop which has project_id
        if is_local and project_info is None:
            return {"success": False, "output": "Local workspace detected but bridge forwarding not configured in this context."}
    registry = get_tool_registry(workspace) if workspace is not None and not is_local else TOOL_REGISTRY
    # For local, we will handle forwarding in the caller (stream_agent_loop) instead
    if is_local:
        # This will be handled by the caller with proper project_id
        return {"success": False, "output": "Local tool execution should be forwarded via bridge (caller handles)."}
    entry = registry.get(tool)
    if not entry:
        return {"success": False, "output": f"Unknown tool: {tool}"}
    try:
        fn = entry["fn"]
        result = fn(**inp)
        if isinstance(result, dict) and "success" in result:
            if "output" in result:
                result["output"] = mask_secrets(str(result["output"]))
            return result
        return {"success": True, "output": mask_secrets(str(result))}
    except Exception as e:
        return {"success": False, "output": f"Tool {tool} failed: {e}"}


def is_shell_dangerous(tool: str, inp: Dict[str, Any]) -> bool:
    if tool != "run_command":
        return False
    cmd = inp.get("command", "")
    return is_dangerous_command(cmd)


async def stream_agent_loop(
    *,
    user_message: str,
    mode: str,
    model: Optional[str],
    history: List[Dict[str, str]],
    workspace: Path | None = None,
    project_info: Dict[str, Any] | None = None,
    user_id: Optional[str] = None,
    project_id: Optional[str] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Core agent loop — yields structured events (workspace-aware, local bridge support)."""
    system = build_system_prompt(mode or "build")
    is_local = bool(project_info and is_local_workspace(project_info.get("workspace", "")))
    if project_info:
        proj_ctx = f"\n\nCURRENT PROJECT:\nName: {project_info.get('name','')}\nWorkspace: {project_info.get('workspace','')}\nStack: {project_info.get('stack','')}\nTemplate: {project_info.get('template','')}\n"
        if project_info.get("description"):
            proj_ctx += f"Description: {project_info['description']}\n"
        if is_local:
            proj_ctx += "Workspace type: LOCAL (files are on user's Windows PC, accessed via Local Bridge)\n"
        system += proj_ctx
        if workspace is not None and not is_local:
            system += f"\nAll file paths are relative to this project's workspace root. Do not use absolute paths.\n"
        if is_local:
            system += "\nAll file paths are relative to the LOCAL project root on the user's PC. Use relative paths only.\n"
    # Seed messages: system + optional history + current task (trimmed for TPM)
    messages: List[Dict[str, str]] = [{"role": "system", "content": system}]
    for m in history[-8:]:
        if m.get("role") in ("user", "assistant") and m.get("content"):
            messages.append({"role": m["role"], "content": m["content"][:1200]})
    messages.append({"role": "user", "content": user_message[:2000]})

    # Always start with a quick project inspection to ground the LLM
    yield {"type": "thinking", "content": "Inspecting project…"}
    if is_local and user_id and project_id:
        try:
            from app.api.bridge import forward_tool_to_bridge
            insp = await forward_tool_to_bridge(user_id, project_id, "inspect_project", {}, timeout=15.0)
        except Exception as e:
            insp = {"success": False, "output": f"Local bridge error: {e}"}
    else:
        insp = await execute_tool("inspect_project", {}, mode, workspace=workspace, project_info=project_info)
    yield {"type": "tool_start", "tool": "inspect_project", "input": {}}
    yield {"type": "tool_result", "tool": "inspect_project", "success": insp["success"], "output": insp["output"][:3000]}
    messages.append({"role": "assistant", "content": json.dumps({"tool": "inspect_project", "input": {}})})
    messages.append({"role": "user", "content": f"Tool inspect_project result:\n{insp['output'][:2500]}"})

    # Main loop
    changed_files: List[str] = []
    for step in range(MAX_STEPS):
        yield {"type": "thinking", "content": f"Planning step {step+1}…"}
        llm_text = await call_llm(messages, model=model)
        tc = parse_tool_call(llm_text)
        # Fallback for write_file with unescaped content
        if tc is None and is_likely_tool_call(llm_text):
            tc = try_fix_unescaped_write(llm_text)
            if tc and tc.get("tool") == "write_file":
                # Validate path
                if not tc["input"].get("path"):
                    tc = None
        if tc is None:
            if is_likely_tool_call(llm_text):
                truncated = llm_text.count("{") != llm_text.count("}") or len(llm_text) > 3500
                if truncated:
                    msg = "Your tool JSON was truncated (file too large for one turn). Please retry the same file with a smaller chunk (under 80 lines) and ensure valid JSON escaping (\\\" for quotes, \\n for newlines)."
                else:
                    msg = "Your tool JSON was malformed (likely unescaped quotes/newlines in content). Please ensure content escapes \" as \\\" and newlines as \\n and output ONLY valid JSON. Example: {\"tool\":\"write_file\",\"input\":{\"path\":\"a.txt\",\"content\":\"hello\\nworld\"}}"
                yield {"type": "tool_result", "tool": "unknown", "success": False, "output": msg}
                messages.append({"role": "assistant", "content": llm_text})
                messages.append({"role": "user", "content": msg})
                continue
            if not llm_text or llm_text.startswith("LLM error"):
                yield {"type": "error", "message": llm_text or "Empty LLM response"}
                break
            yield {"type": "completed", "content": llm_text, "changedFiles": changed_files}
            break

        tool = tc["tool"]
        inp = tc["input"] or {}

        # Permission: dangerous shell requires approval event
        if is_shell_dangerous(tool, inp):
            yield {
                "type": "approval_required",
                "tool": tool,
                "input": inp,
                "reason": "This command may be destructive or affect system state. Allow?",
            }
            # For now, skip execution and inform LLM
            msg = f"Tool {tool} requires user approval and was not executed. Ask the user to approve, or propose a safer alternative."
            messages.append({"role": "assistant", "content": json.dumps(tc)})
            messages.append({"role": "user", "content": msg})
            # Also emit so frontend can show
            yield {"type": "tool_result", "tool": tool, "success": False, "output": msg}
            continue

        # Delete also requires approval-style event (but we still execute in build after emitting)
        if tool == "delete_file":
            yield {"type": "approval_required", "tool": tool, "input": inp, "reason": "Deleting files is destructive."}
            # Count as soft gate: still allow but frontend will have shown dialog.
            # In strict mode you'd wait; here we continue.

        yield {"type": "tool_start", "tool": tool, "input": inp}
        if is_local and user_id and project_id:
            try:
                from app.api.bridge import forward_tool_to_bridge
                # Map tool timeout: longer for run_command
                tmo = 60.0 if tool == "run_command" else 30.0
                result = await forward_tool_to_bridge(user_id, project_id, tool, inp, timeout=tmo)
            except Exception as e:
                result = {"success": False, "output": f"Local bridge error: {e}"}
        else:
            result = await execute_tool(tool, inp, mode, workspace=workspace, project_info=project_info)
        # Track changed files
        if tool in ("write_file", "edit_file") and result.get("success"):
            p = inp.get("path")
            if p and p not in changed_files:
                changed_files.append(p)
                yield {"type": "file_changed", "path": p}
        if tool == "run_command":
            yield {"type": "command_started", "command": inp.get("command", "")}
            # run_command result already contains exit code header
            yield {"type": "command_result", "success": result.get("success", False), "output": result.get("output", "")[:5000]}
        # Regular tool_result (also for commands, but we already emitted command_result)
        if tool != "run_command":
            yield {"type": "tool_result", "tool": tool, "success": result.get("success", False), "output": result.get("output", "")[:6000]}
        else:
            # Already emitted command_result; also emit tool_result for uniform handling
            yield {"type": "tool_result", "tool": tool, "success": result.get("success", False), "output": result.get("output", "")[:6000]}

        # Feed result back to LLM (trimmed)
        messages.append({"role": "assistant", "content": json.dumps(tc)})
        out = result.get("output", "")[:2000]
        messages.append({"role": "user", "content": f"Tool {tool} result (success={result.get('success')}):\n{out}"})

        # Safety: avoid infinite loops if LLM keeps emitting same tool
        await asyncio.sleep(0.05)
    else:
        yield {"type": "completed", "content": "Reached step limit. Task may be incomplete — review tool outputs above.", "changedFiles": changed_files}
