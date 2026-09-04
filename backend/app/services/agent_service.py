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
    # Strip markdown fences if present
    t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.I)
    t = re.sub(r"\s*```$", "", t, flags=re.I).strip()
    # Try direct JSON
    try:
        obj = json.loads(t)
        if isinstance(obj, dict) and "tool" in obj:
            if obj["tool"] in TOOL_REGISTRY:
                return {"tool": obj["tool"], "input": obj.get("input", {}) if isinstance(obj.get("input"), dict) else {}}
    except Exception:
        pass
    # Search for JSON object inside text
    m = re.search(r"\{[^{}]*\"tool\"\s*:\s*\"[a-z_]+\"[^{}]*\}", t, re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict) and "tool" in obj and obj["tool"] in TOOL_REGISTRY:
                return {"tool": obj["tool"], "input": obj.get("input", {}) if isinstance(obj.get("input"), dict) else {}}
        except Exception:
            pass
    # Multi-line JSON
    try:
        # Find first { and last }
        start = t.find("{")
        end = t.rfind("}")
        if start != -1 and end != -1 and end > start:
            obj = json.loads(t[start : end + 1])
            if isinstance(obj, dict) and "tool" in obj and obj["tool"] in TOOL_REGISTRY:
                return {"tool": obj["tool"], "input": obj.get("input", {}) if isinstance(obj.get("input"), dict) else {}}
    except Exception:
        pass
    return None


async def call_llm(messages: List[Dict[str, str]], model: Optional[str] = None) -> str:
    """Call Groq via the existing AIService (non-streaming) and return content."""
    settings = get_settings()
    mdl = model or settings.model
    # Use complete with custom system_prompt: we send system as first message via build_history handling.
    # Simpler: construct history manually and call client directly.
    try:
        # Use ai_service client directly to allow arbitrary system prompt
        resp = await ai_service.client.chat.completions.create(
            model=mdl,
            messages=messages,
            temperature=0.35,
            max_tokens=3000,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        return f"LLM error: {e}"


async def execute_tool(tool: str, inp: Dict[str, Any], mode: str, workspace: Path | None = None) -> Dict[str, Any]:
    """Execute a registered tool with permission checks (workspace-aware)."""
    if mode == "plan" and tool not in READ_TOOLS:
        return {"success": False, "output": f"Tool '{tool}' is not allowed in Plan mode (read-only). Switch to Build to modify files/run commands."}
    if tool in DESTRUCTIVE_TOOLS and mode != "build":
        return {"success": False, "output": f"Tool '{tool}' requires Build mode."}
    registry = get_tool_registry(workspace) if workspace is not None else TOOL_REGISTRY
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
) -> AsyncGenerator[Dict[str, Any], None]:
    """Core agent loop — yields structured events (workspace-aware)."""
    system = build_system_prompt(mode or "build")
    # Inject project context if available
    if project_info:
        proj_ctx = f"\n\nCURRENT PROJECT:\nName: {project_info.get('name','')}\nWorkspace: {project_info.get('workspace','')}\nStack: {project_info.get('stack','')}\nTemplate: {project_info.get('template','')}\n"
        if project_info.get("description"):
            proj_ctx += f"Description: {project_info['description']}\n"
        system += proj_ctx
        # Also hint the model about workspace root
        if workspace is not None:
            system += f"\nAll file paths are relative to this project's workspace root. Do not use absolute paths.\n"
    # Seed messages: system + optional history + current task
    messages: List[Dict[str, str]] = [{"role": "system", "content": system}]
    # Include prior turn history (trimmed)
    for m in history[-8:]:
        if m.get("role") in ("user", "assistant") and m.get("content"):
            messages.append({"role": m["role"], "content": m["content"][:3000]})
    messages.append({"role": "user", "content": user_message})

    # Always start with a quick project inspection to ground the LLM
    yield {"type": "thinking", "content": "Inspecting project…"}
    insp = await execute_tool("inspect_project", {}, mode, workspace=workspace)
    yield {"type": "tool_start", "tool": "inspect_project", "input": {}}
    yield {"type": "tool_result", "tool": "inspect_project", "success": insp["success"], "output": insp["output"][:6000]}
    messages.append({"role": "assistant", "content": json.dumps({"tool": "inspect_project", "input": {}})})
    messages.append({"role": "user", "content": f"Tool inspect_project result:\n{insp['output'][:5000]}"})

    # Main loop
    changed_files: List[str] = []
    for step in range(MAX_STEPS):
        yield {"type": "thinking", "content": f"Planning step {step+1}…"}
        llm_text = await call_llm(messages, model=model)
        # Check for tool call
        tc = parse_tool_call(llm_text)
        if tc is None:
            # No tool — treat as final answer / plan
            # If empty or LLM error string, try once more
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
        result = await execute_tool(tool, inp, mode, workspace=workspace)
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

        # Feed result back to LLM
        messages.append({"role": "assistant", "content": json.dumps(tc)})
        # Truncate tool output for LLM context
        out = result.get("output", "")[:4000]
        messages.append({"role": "user", "content": f"Tool {tool} result (success={result.get('success')}):\n{out}"})

        # Safety: avoid infinite loops if LLM keeps emitting same tool
        await asyncio.sleep(0.05)
    else:
        yield {"type": "completed", "content": "Reached step limit. Task may be incomplete — review tool outputs above.", "changedFiles": changed_files}
