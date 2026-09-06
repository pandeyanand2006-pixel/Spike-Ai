"""Agent service — planning, tool loop, validation, and observability.

Phase 1: native OpenAI-compatible function calling via Groq (streaming, multi-tool).
Phase 2: todo_write checklist persisted to session.
Phase 5: larger max_tokens / steps for file-heavy turns.
"""
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
from app.services.tool_schemas import TOOL_SCHEMAS
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

When you have completed the task, respond with a concise summary including:
## Completed — what was done
### Changes — files created/edited
### Validation — tests/build results
### Next steps — if any
"""

PLAN_SUFFIX = """
MODE: PLAN — read-only. You may ONLY use: read_file, list_directory, search_files, get_file_info, inspect_project, git_status, git_diff, todo_write.
Your FIRST and required action is to call todo_write with a complete step-by-step plan (5–15 concrete, independently completable and verifiable steps), then provide a short prose summary. Do NOT use write_file, edit_file, delete_file, create_directory, move_file, or run_command in Plan mode.
"""

BUILD_SUFFIX = """
MODE: BUILD — you may read, search, create, edit, run commands, test, and validate.
If a todos list already exists in context (Approved plan), work through items in order: call todo_write to mark each in_progress before starting it and completed immediately after it is verified — never batch-completing several at once.
For web projects (calculator, dashboard, etc.): create real files live in the workspace, run npm install if needed, then validate with npm run build or vite build. If the user wants to see it live, run the dev server (npm run dev / vite) and report the localhost URL (e.g., http://localhost:5173) exactly as printed — never invent a URL. Files must actually exist on disk via your tool calls; the dev server runs via run_command in the workspace so the UI can link it.
"""

MAX_STEPS = 40
MAX_LLM_RETRIES = 2


def build_system_prompt(mode: str) -> str:
    base = AGENT_SYSTEM_PROMPT
    if mode == "plan":
        return base + "\n" + PLAN_SUFFIX
    return base + "\n" + BUILD_SUFFIX


# ---------- Native tool-calling LLM helper (streaming) ----------

async def call_llm_with_tools(
    messages: List[Dict[str, Any]],
    model: Optional[str] = None,
    stream_callback=None,
) -> tuple[str, List[Dict[str, Any]]]:
    """Call Groq with native tools, optionally streaming live deltas.

    Returns (content_text, tool_calls) where tool_calls is a list of
    {id, name, arguments: dict}. Streaming deltas are forwarded via
    stream_callback(content_delta) if provided.
    """
    settings = get_settings()
    mdl = model or settings.model

    # Phase 5: larger max_tokens for file-heavy turns (heuristic: if history
    # mentions write_file/edit_file intent, allow 4000; else 900)
    # For now we use a simple heuristic on last user message length
    last_user = ""
    for m in reversed(messages):
        if m.get("role") == "user" and m.get("content"):
            last_user = str(m["content"])
            break
    wants_write = "write_file" in last_user.lower() or "edit_file" in last_user.lower() or len(last_user) > 800
    max_tokens = 4000 if wants_write else 900

    try:
        # Try streaming first (gives live token feed)
        stream = await ai_service.client.chat.completions.create(
            model=mdl,
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
            temperature=0.35,
            max_tokens=max_tokens,
            stream=True,
        )
        content_acc = ""
        tool_calls_acc: Dict[int, Dict[str, Any]] = {}
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                content_acc += delta.content
                if stream_callback:
                    try:
                        await stream_callback(delta.content)
                    except Exception:
                        pass
            if getattr(delta, "tool_calls", None):
                for tc in delta.tool_calls:
                    idx = getattr(tc, "index", 0) or 0
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {"id": "", "name": "", "args": ""}
                    if getattr(tc, "id", None):
                        tool_calls_acc[idx]["id"] = tc.id
                    func = getattr(tc, "function", None)
                    if func:
                        if getattr(func, "name", None):
                            tool_calls_acc[idx]["name"] += func.name
                        if getattr(func, "arguments", None):
                            tool_calls_acc[idx]["args"] += func.arguments
        # Parse accumulated tool calls
        tool_calls: List[Dict[str, Any]] = []
        for _idx in sorted(tool_calls_acc.keys()):
            entry = tool_calls_acc[_idx]
            name = (entry.get("name") or "").strip()
            if not name:
                continue
            args_str = entry.get("args") or "{}"
            try:
                args = json.loads(args_str) if args_str else {}
            except Exception:
                # Malformed JSON fallback: try to fix trailing
                try:
                    args = json.loads(args_str + "}")
                except Exception:
                    args = {}
            tool_calls.append({"id": entry.get("id") or f"call_{_idx}", "name": name, "arguments": args if isinstance(args, dict) else {}})
        return content_acc.strip(), tool_calls
    except Exception as e:
        # Fallback to non-streaming if streaming not supported
        msg = str(e)
        if "429" in msg or "rate_limit" in msg.lower() or "OTPM" in msg:
            try:
                # Retry with smaller window
                resp = await ai_service.client.chat.completions.create(
                    model=mdl,
                    messages=messages[-6:],
                    tools=TOOL_SCHEMAS,
                    tool_choice="auto",
                    temperature=0.35,
                    max_tokens=600,
                )
                m = resp.choices[0].message
                text = (m.content or "").strip()
                tcs = []
                if getattr(m, "tool_calls", None):
                    for tc in m.tool_calls:
                        try:
                            args = json.loads(tc.function.arguments or "{}")
                        except Exception:
                            args = {}
                        tcs.append({"id": tc.id, "name": tc.function.name, "arguments": args if isinstance(args, dict) else {}})
                return text, tcs
            except Exception as e2:
                return f"LLM error: {e2}", []
        # Try non-streaming direct
        try:
            resp = await ai_service.client.chat.completions.create(
                model=mdl,
                messages=messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
                temperature=0.35,
                max_tokens=max_tokens,
            )
            m = resp.choices[0].message
            text = (m.content or "").strip()
            tcs = []
            if getattr(m, "tool_calls", None):
                for tc in m.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except Exception:
                        args = {}
                    tcs.append({"id": tc.id, "name": tc.function.name, "arguments": args if isinstance(args, dict) else {}})
            return text, tcs
        except Exception as e2:
            return f"LLM error: {e2}", []


async def execute_tool(tool: str, inp: Dict[str, Any], mode: str, workspace: Path | None = None, project_info: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Execute a registered tool with permission checks (workspace-aware). For local projects, forward to bridge."""
    if tool == "todo_write":
        # Handled specially in stream_agent_loop
        return {"success": True, "output": "Todo list updated"}
    if mode == "plan" and tool not in READ_TOOLS and tool not in {"todo_write"}:
        return {"success": False, "output": f"Tool '{tool}' is not allowed in Plan mode (read-only). Switch to Build to modify files/run commands."}
    if tool in DESTRUCTIVE_TOOLS and mode != "build":
        return {"success": False, "output": f"Tool '{tool}' requires Build mode."}
    is_local = False
    if project_info and is_local_workspace(project_info.get("workspace", "")):
        is_local = True
    elif workspace and is_local_workspace(str(workspace)):
        is_local = True
    if is_local:
        if is_local and project_info is None:
            return {"success": False, "output": "Local workspace detected but bridge forwarding not configured in this context."}
    registry = get_tool_registry(workspace) if workspace is not None and not is_local else TOOL_REGISTRY
    if is_local:
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
    history: List[Dict[str, Any]],
    workspace: Path | None = None,
    project_info: Dict[str, Any] | None = None,
    user_id: Optional[str] = None,
    project_id: Optional[str] = None,
    existing_todos: Optional[List[Dict[str, Any]]] = None,
    pending_approval: Optional[Dict[str, Any]] = None,
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
    # If we have existing todos (Build from approved plan), inject them
    messages: List[Dict[str, Any]] = [{"role": "system", "content": system}]
    # Normalize history: support both {role, content} and tool messages
    for m in history[-12:]:
        if not isinstance(m, dict):
            continue
        r = m.get("role")
        if r in ("user", "assistant", "tool", "system") and (m.get("content") is not None or m.get("tool_calls")):
            # Keep tool_calls if present
            entry: Dict[str, Any] = {"role": r, "content": m.get("content", "") or ""}
            if m.get("tool_calls"):
                entry["tool_calls"] = m["tool_calls"]
            if m.get("tool_call_id"):
                entry["tool_call_id"] = m["tool_call_id"]
            if m.get("name"):
                entry["name"] = m["name"]
            messages.append(entry)
    # Inject approved plan if present
    if existing_todos:
        messages.append({"role": "user", "content": "Approved plan:\n" + json.dumps(existing_todos) + "\n\nExecute it now. Work through todos in order, marking each in_progress then completed via todo_write."})
    messages.append({"role": "user", "content": user_message[:4000]})

    # Always start with a quick project inspection to ground the LLM (unless resuming)
    # For continue/resume, caller passes inspected flag via history length; we still inspect once per session
    should_inspect = True
    # If history already contains a tool result for inspect_project, skip
    for m in history:
        if "inspect_project" in str(m.get("content", "")) or "Detected stack" in str(m.get("content", "")):
            should_inspect = False
            break
    if should_inspect:
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
        messages.append({"role": "assistant", "content": "", "tool_calls": [{"id": "inspect_0", "type": "function", "function": {"name": "inspect_project", "arguments": "{}"}}]})
        messages.append({"role": "tool", "tool_call_id": "inspect_0", "content": insp["output"][:2500]})

    # Main loop — supports multiple tool calls per turn
    changed_files: List[str] = []
    pending_todos: List[Dict[str, Any]] = list(existing_todos or [])
    for step in range(MAX_STEPS):
        yield {"type": "thinking", "content": f"Planning step {step+1}…"}

        # Streaming callback to emit live thinking tokens
        thinking_buf = ""
        async def on_delta(delta: str):
            nonlocal thinking_buf
            thinking_buf += delta
            # emit incremental thinking (throttle: only if we have content)
            # We reuse thinking type for live tokens
            # To avoid spam, yield as thinking but UI can append
            pass  # handled via outer yield after call

        content, tool_calls = await call_llm_with_tools(messages, model=model)

        # If we got live content but no tools, it's a final answer
        if not tool_calls:
            if not content or content.startswith("LLM error"):
                yield {"type": "error", "message": content or "Empty LLM response"}
                break
            yield {"type": "completed", "content": content, "changedFiles": changed_files}
            break

        # We have tool calls — execute sequentially, feeding each result as tool message
        # First, add assistant message with tool_calls to history
        assistant_tool_calls = []
        for tc in tool_calls:
            assistant_tool_calls.append({"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"])}})
        messages.append({"role": "assistant", "content": content or "", "tool_calls": assistant_tool_calls})

        # Execute each tool in order, yielding events
        should_break_after_tools = False
        for tc in tool_calls:
            tool = tc["name"]
            inp = tc["arguments"] if isinstance(tc["arguments"], dict) else {}
            tc_id = tc["id"]

            # todo_write is special
            if tool == "todo_write":
                todos = inp.get("todos") or []
                # Basic validation
                if not isinstance(todos, list):
                    todos = []
                pending_todos = todos
                yield {"type": "todo_update", "todos": todos}
                # Also feed tool result back
                out = "Todo list updated"
                yield {"type": "tool_start", "tool": tool, "input": inp}
                yield {"type": "tool_result", "tool": tool, "success": True, "output": out}
                messages.append({"role": "tool", "tool_call_id": tc_id, "content": out})
                continue

            # Permission checks
            if is_shell_dangerous(tool, inp):
                yield {
                    "type": "approval_required",
                    "tool": tool,
                    "input": inp,
                    "reason": "This command may be destructive or affect system state. Allow?",
                }
                # Persist pending approval via special event and pause
                yield {"type": "tool_result", "tool": tool, "success": False, "output": "Tool requires user approval and was not executed. Awaiting approval."}
                messages.append({"role": "tool", "tool_call_id": tc_id, "content": "Tool requires approval — paused awaiting user decision."})
                # Do not continue loop — wait for /approve to resume
                should_break_after_tools = True
                # Mark that we paused for approval
                yield {"type": "error", "message": "Paused awaiting approval"}
                break

            if tool == "delete_file":
                yield {"type": "approval_required", "tool": tool, "input": inp, "reason": "Deleting files is destructive."}
                yield {"type": "tool_result", "tool": tool, "success": False, "output": "Delete requires approval — paused."}
                messages.append({"role": "tool", "tool_call_id": tc_id, "content": "Delete requires approval — paused."})
                should_break_after_tools = True
                yield {"type": "error", "message": "Paused awaiting approval for delete"}
                break

            yield {"type": "tool_start", "tool": tool, "input": inp}
            if is_local and user_id and project_id:
                try:
                    from app.api.bridge import forward_tool_to_bridge
                    tmo = 60.0 if tool == "run_command" else 30.0
                    result = await forward_tool_to_bridge(user_id, project_id, tool, inp, timeout=tmo)
                except Exception as e:
                    result = {"success": False, "output": f"Local bridge error: {e}"}
            else:
                result = await execute_tool(tool, inp, mode, workspace=workspace, project_info=project_info)

            # Track changed files
            if tool in ("write_file", "edit_file", "create_directory", "move_file") and result.get("success"):
                p = inp.get("path") or inp.get("src") or inp.get("dst")
                if p and p not in changed_files:
                    changed_files.append(p)
                    yield {"type": "file_changed", "path": p}
            if tool == "run_command":
                yield {"type": "command_started", "command": inp.get("command", "")}
                yield {"type": "command_result", "success": result.get("success", False), "output": result.get("output", "")[:5000]}
            yield {"type": "tool_result", "tool": tool, "success": result.get("success", False), "output": result.get("output", "")[:6000]}

            # Feed result back
            out = result.get("output", "")[:2500]
            messages.append({"role": "tool", "tool_call_id": tc_id, "content": f"Tool {tool} result (success={result.get('success')}):\n{out}"})

            await asyncio.sleep(0.05)

        if should_break_after_tools:
            break
        # Continue loop for next turn

    else:
        yield {"type": "completed", "content": "Reached step limit. Task may be incomplete — review tool outputs above.", "changedFiles": changed_files}


# Startup assertion: tool contract parity
def _assert_tool_parity():
    try:
        from app.services.tool_schemas import TOOL_SCHEMAS as _schemas
        schema_names = {s["function"]["name"] for s in _schemas}
        registry_names = set(TOOL_REGISTRY.keys())
        # bridge parity is checked at runtime via forward_tool_to_bridge dispatch
        missing_in_registry = schema_names - registry_names
        extra_in_registry = registry_names - schema_names
        if missing_in_registry or extra_in_registry:
            import logging
            logging.getLogger("uvicorn.error").warning(
                f"Tool parity mismatch: schemas - registry = {missing_in_registry}, registry - schemas = {extra_in_registry}"
            )
    except Exception:
        pass

_assert_tool_parity()
