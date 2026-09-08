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

AGENT_SYSTEM_PROMPT = """You are Spike Agent, an autonomous software engineering agent comparable to OpenCode, Cline, OpenHands, and Goose.

You work directly on the user's project workspace. You are NOT a chatbot — you must use tools to inspect and modify the project instead of only describing code.

Autonomous loop (UNDERSTAND → INSPECT → DETECT → PLAN → EXECUTE → OBSERVE → DIAGNOSE → REPAIR → VERIFY → COMPLETE):
1. Understand the task. Detect technology + environment before acting.
2. Inspect workspace: inspect_project, detect_environment, list_directory, read_file, search_files.
3. Detect actual toolchains (java/mvn/gradle/node/python/cmake/go/rust/flutter/docker etc.) via detect_environment — never assume a tool exists.
4. Create a plan via todo_write for multi-step tasks (5–15 verifiable steps); keep it updated.
5. Execute with real files/commands — create/edit files, run commands, capture stdout/stderr + exit codes.
6. Observe output. If a command fails, diagnose the real cause (Compilation/Dependency/Package/Type/Syntax/Runtime/Config/Port/DB/Test/Build/Import/Permission/Toolchain), then repair and retry.
7. For arbitrary tech (Java/Spring/Maven/Gradle, C/C++/CMake, Python/Django/FastAPI, Node/React/Next/Vue, Flutter/Dart, Go, Rust, .NET, Android, Docker): infer correct build/test commands from project files instead of using hardcoded templates. Prefer wrappers: ./mvnw, ./gradlew when present.
8. Never stop after merely creating files. Verify: run the project's actual build/test (mvn test / gradle test / npm run build / npm test / pytest / cargo test / go test ./... / flutter test / ctest / dotnet test etc.) via verify_project or run_command and report genuine results.
9. Prefer minimal, targeted changes. Preserve unrelated code and user modifications.

Hard rules:
- Never fabricate files, commands, test results, URLs, or tool availability. Use tools and real execution.
- Inspect relevant files before editing them.
- Search the codebase when necessary.
- Never expose secrets (.env, keys). Mask them.
- Never perform destructive operations (rm -rf, git reset --hard, delete_file on critical paths) without approval.
- Stay inside the authorized workspace.
- Do not reveal private chain-of-thought. Show concise action summaries.
- Ask for clarification only when genuinely necessary; otherwise make reasonable assumptions and continue.
- Finish the task completely whenever possible.

CRITICAL FILE EDITING RULE — you must follow this or your tool call will fail:
- When editing or writing a file, if the new content is large, prefer several smaller edit_file calls (each replacing a small, uniquely-matched old_string) over one write_file/edit_file call with a huge new_string.
- Never pass more than ~150 lines of content in a single tool call's parameter value.
- If you need to add many new lines (e.g. new HTML sections), insert them incrementally by targeting small anchor points, not by rewriting the whole file at once.
- Keep each file operation focused and verifiable.

When you have completed the task, respond with a concise summary including:
## Completed — what was done
### Changes — files created/edited
### Validation — tests/build results
### Next steps — if any
"""

PLAN_SUFFIX = """
MODE: PLAN — read-only. You may ONLY use: read_file, list_directory, search_files, get_file_info, inspect_project, detect_environment, git_status, git_diff, todo_write, verify_project.
Your FIRST and required action is to call todo_write with a complete step-by-step plan (5–15 concrete, independently completable and verifiable steps), then provide a short prose summary. Do NOT use write_file, edit_file, delete_file, create_directory, move_file, or run_command in Plan mode.
"""

BUILD_SUFFIX = """
MODE: BUILD — you may read, search, create, edit, run commands, test, and validate autonomously.
Loop: INSPECT → DETECT ENVIRONMENT → PLAN (todo_write) → EXECUTE (files/commands) → OBSERVE (exit codes, stdout/stderr) → DIAGNOSE (classify failure) → REPAIR (targeted edit) → RETRY → VERIFY (verify_project / real build/test) → COMPLETE only after verification passes.
If a todos list already exists in context (Approved plan), work through items in order: call todo_write to mark each in_progress before starting it and completed immediately after it is verified — never batch-completing several at once.
For empty workspaces: detect JDK/Maven/Gradle/Node/Python/etc. via detect_environment, choose an available toolchain (prefer wrappers ./mvnw/./gradlew), create the full project structure, install deps, then build/test.
For web projects (calculator, dashboard, etc.): create real files live in the workspace, run npm install if needed, then validate with npm run build or vite build. If the user wants to see it live, run the dev server (npm run dev / vite) and report the localhost URL (e.g., http://localhost:5173) exactly as printed — never invent a URL. Files must actually exist on disk via your tool calls; the dev server runs via run_command in the workspace so the UI can link it.
For backend/API projects: build, start, smoke-test a safe endpoint, report real response, then stop the server if appropriate.
For any project: always finish with verification. If verification is blocked (missing tool, insufficient env), state the actual blocker: "Implementation completed, but verification was blocked because: <real reason>".
"""

def _get_max_steps() -> int:
    try:
        return int(get_settings().agent_max_steps or 60)
    except Exception:
        return 60

MAX_STEPS = 60  # overridden at runtime via _get_max_steps()
MAX_LLM_RETRIES = 2

# ---------- Model fallback / daily-cap tracking (Fix #1) ----------
import time as _time
from datetime import datetime, timezone as _tz

_daily_exhausted: Dict[str, float] = {}  # model -> expiry timestamp (seconds since epoch)


def _next_midnight_ts() -> float:
    now = datetime.now(_tz.utc)
    # next UTC midnight
    tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # if we are already past midnight today, tomorrow is +1 day
    import datetime as _dt
    tomorrow = tomorrow + _dt.timedelta(days=1)
    return tomorrow.timestamp()


def _is_exhausted(model: str) -> bool:
    exp = _daily_exhausted.get(model)
    if exp is None:
        return False
    if _time.time() < exp:
        return True
    # expired — clear
    _daily_exhausted.pop(model, None)
    return False


def _mark_exhausted(model: str, err_text: str):
    low = (err_text or "").lower()
    is_tpd = "tokens per day" in low or "tpd" in low or "per day" in low
    is_tpm = "tokens per minute" in low or "tpm" in low or "per minute" in low
    if is_tpd:
        _daily_exhausted[model] = _next_midnight_ts()
    elif is_tpm:
        # per-minute: short backoff, not daily
        _daily_exhausted[model] = _time.time() + 65
    else:
        # generic rate_limit_exceeded without detail — treat as per-minute
        if "rate_limit" in low or "429" in low:
            _daily_exhausted[model] = _time.time() + 65


def _is_tpd_error(text: str) -> bool:
    low = (text or "").lower()
    return "tokens per day" in low or " tpd" in low


def _is_model_error(text: str) -> bool:
    low = (text or "").lower()
    return "model_not_found" in low or "decommissioned" in low or "does not exist" in low


def build_system_prompt(mode: str) -> str:
    base = AGENT_SYSTEM_PROMPT
    if mode == "plan":
        return base + "\n" + PLAN_SUFFIX
    return base + "\n" + BUILD_SUFFIX


def _extract_failed_generation_text(exc: Exception) -> Optional[str]:
    """Best-effort extract `failed_generation` raw text from Groq tool_use_failed error."""
    # Groq's error body is often in exc.body or exc.response JSON or str(exc)
    for attr in ("body", "response", "error"):
        try:
            val = getattr(exc, attr, None)
            if val is not None:
                if isinstance(val, dict):
                    # look for failed_generation in dict
                    if "failed_generation" in val:
                        return str(val["failed_generation"])
                    err = val.get("error", {})
                    if isinstance(err, dict) and "failed_generation" in err:
                        return str(err["failed_generation"])
                if hasattr(val, "json"):
                    try:
                        j = val.json()
                        if isinstance(j, dict):
                            if "failed_generation" in j:
                                return str(j["failed_generation"])
                            err = j.get("error", {})
                            if isinstance(err, dict) and "failed_generation" in err:
                                return str(err["failed_generation"])
                    except Exception:
                        pass
                s = str(val)
                if "failed_generation" in s or "<function=" in s:
                    # try to pull JSON substring
                    import re as _re
                    m = _re.search(r'"failed_generation"\s*:\s*"((?:\\.|[^"])*)"', s, _re.S)
                    if m:
                        try:
                            return json.loads('"' + m.group(1) + '"')
                        except Exception:
                            return m.group(1)
                    if "<function=" in s:
                        return s
        except Exception:
            continue
    s = str(exc)
    if "failed_generation" in s or "<function=" in s:
        return s
    return None


def _recover_from_failed_generation(exc: Exception) -> Optional[List[Dict[str, Any]]]:
    """Parse Hermes-style <function=NAME><parameter=KEY>VALUE</parameter> into tool_calls."""
    raw = _extract_failed_generation_text(exc)
    if not raw:
        return None
    fn_match = re.search(r"<function=([a-zA-Z_][a-zA-Z0-9_]*)\s*>", raw)
    if not fn_match:
        return None
    tool_name = fn_match.group(1).strip()
    # Only recover known tools
    known = {s["function"]["name"] for s in TOOL_SCHEMAS}
    if tool_name not in known:
        return None
    params: Dict[str, Any] = {}
    for pm in re.finditer(r"<parameter=([a-zA-Z_][a-zA-Z0-9_]*)\s*>\n?(.*?)\n?</parameter>", raw, re.S):
        key = pm.group(1)
        val = pm.group(2)
        # Groq escapes inside; unescape common entities
        # Keep raw content as-is except strip leading/trailing newline added by regex
        params[key] = val
    if not params:
        return None
    # Validate required params presence for basic safety
    # Allow partial but need at least path for file tools
    if tool_name in ("write_file", "edit_file", "read_file", "delete_file", "create_directory", "get_file_info", "git_diff") and "path" not in params:
        return None
    if tool_name == "move_file" and ("src" not in params or "dst" not in params):
        # bridge uses dst/dest variants
        if not (("src" in params or "path" in params) and ("dst" in params or "dest" in params or "new_path" in params)):
            return None
        if "path" in params and "src" not in params:
            params["src"] = params.pop("path")
        if "dest" in params and "dst" not in params:
            params["dst"] = params.pop("dest")
    # For edit_file, map content variations
    return [{"id": "recovered_0", "name": tool_name, "arguments": params}]


# ---------- Native tool-calling LLM helper (streaming) with fallback chain ----------

async def call_llm_with_tools(
    messages: List[Dict[str, Any]],
    model: Optional[str] = None,
    stream_callback=None,
    _retry_for_recovery: bool = True,
) -> tuple[str, List[Dict[str, Any]]]:
    """Provider-aware tool-calling LLM with Groq fallback and local-model support.

    If settings.llm_provider != "groq", routes via provider_adapter
    (OpenRouter / Gemini / openai_compatible / Ollama) before falling back
    to the native Groq chain. Preserves TPD/rate-limit tracking.
    """
    settings = get_settings()
    # Try provider abstraction first when not groq
    provider_name = getattr(settings, "llm_provider", "groq") or "groq"
    if provider_name != "groq":
        try:
            from app.services.provider_adapter import get_agent_provider
            provider, prov_model = get_agent_provider()
            # Only use adapter if it isn't plain Groq
            if getattr(provider, "name", "") != "groq":
                mdl = model or prov_model or settings.model
                # quick availability check for local providers
                if provider_name in ("ollama", "local", "openai_compatible") and mdl:
                    # try to check local availability but don't block — just attempt
                    pass
                last_user = ""
                for m in reversed(messages):
                    if m.get("role") == "user" and m.get("content"):
                        last_user = str(m["content"])
                        break
                max_tokens = 4000 if ("write_file" in last_user.lower() or len(last_user) > 800) else 900
                text, tcs = await provider.chat_with_tools(messages, TOOL_SCHEMAS, mdl, max_tokens=max_tokens, stream=True)
                # If provider returns empty/error, let Groq fallback handle it
                if not (text.startswith("LLM error") or text.startswith("ALL_MODELS_EXHAUSTED")):
                    return text, tcs
                # otherwise fall through to Groq fallback
        except Exception as e:
            import logging
            logging.getLogger("uvicorn.error").warning(f"Provider {provider_name} failed, falling back to Groq: {e}")
    # Build effective fallback chain (Groq path)
    chain = list(getattr(settings, "model_fallback_chain", [settings.model]))
    if model and model not in chain:
        chain = [model] + [m for m in chain if m != model]
    # Remove exhausted models for this calendar day (but keep at least one)
    available = [m for m in chain if not _is_exhausted(m)]
    if not available:
        return "ALL_MODELS_EXHAUSTED: All models are at today's usage limit — try again later (daily quota resets at UTC midnight).", []

    last_user = ""
    for m in reversed(messages):
        if m.get("role") == "user" and m.get("content"):
            last_user = str(m["content"])
            break
    wants_write = "write_file" in last_user.lower() or "edit_file" in last_user.lower() or len(last_user) > 800
    max_tokens = 4000 if wants_write else 900

    last_err: Optional[str] = None
    for idx, mdl in enumerate(available):
        try:
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
                        cidx = getattr(tc, "index", 0) or 0
                        if cidx not in tool_calls_acc:
                            tool_calls_acc[cidx] = {"id": "", "name": "", "args": ""}
                        if getattr(tc, "id", None):
                            tool_calls_acc[cidx]["id"] = tc.id
                        func = getattr(tc, "function", None)
                        if func:
                            if getattr(func, "name", None):
                                tool_calls_acc[cidx]["name"] += func.name
                            if getattr(func, "arguments", None):
                                tool_calls_acc[cidx]["args"] += func.arguments
            tool_calls: List[Dict[str, Any]] = []
            for _cidx in sorted(tool_calls_acc.keys()):
                entry = tool_calls_acc[_cidx]
                name = (entry.get("name") or "").strip()
                if not name:
                    continue
                args_str = entry.get("args") or "{}"
                try:
                    args = json.loads(args_str) if args_str else {}
                except Exception:
                    try:
                        args = json.loads(args_str + "}")
                    except Exception:
                        args = {}
                tool_calls.append({"id": entry.get("id") or f"call_{_cidx}", "name": name, "arguments": args if isinstance(args, dict) else {}})
            return content_acc.strip(), tool_calls
        except Exception as e:
            err = str(e)
            last_err = err
            # tool_use_failed recovery (before rate-limit fallback)
            if _retry_for_recovery and ("tool_use_failed" in err or "Failed to call a function" in err):
                recovered = _recover_from_failed_generation(e)
                if recovered:
                    return "", recovered
                try:
                    messages.append({
                        "role": "user",
                        "content": (
                            "Your last tool call failed because the content was too large or "
                            "malformed. Retry the SAME edit but split it into a smaller "
                            "edit_file call (under 100 lines) targeting one small, unique "
                            "anchor string."
                        ),
                    })
                    return await call_llm_with_tools(messages, model=model, stream_callback=stream_callback, _retry_for_recovery=False)
                except Exception:
                    pass
            if _is_model_error(err):
                continue
            # Rate limit handling
            is_rl = "429" in err or "rate_limit" in err.lower() or "rateLimit" in err
            if is_rl:
                # Mark and decide TPD vs TPM
                _mark_exhausted(mdl, err)
                is_tpd = _is_tpd_error(err)
                if is_tpd:
                    # Daily cap — try next model immediately
                    continue
                # Per-minute: wait once then retry same model once, else next model
                try:
                    await asyncio.sleep(7)
                    # one retry of same model non-streaming with smaller window
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
                    # if retry also rate-limited, mark and move to next model
                    if "429" in str(e2) or "rate_limit" in str(e2).lower():
                        _mark_exhausted(mdl, str(e2))
                    continue
            # Non-rate-limit error: try next model only if we have one and error looks model-specific
            # For tool_use_failed we already handled; for other errors, don't fallback aggressively
            if idx < len(available) - 1 and ("tool_use_failed" not in err and "LLM error" not in err):
                # For generic errors, don't exhaust chain — return immediately
                break
            # Fall through to try next model for rate-limit only; otherwise break
            if not is_rl:
                break
            continue

    # If we exhausted all models due to TPD
    if last_err and ("tokens per day" in last_err.lower() or "tpd" in last_err.lower()):
        return "ALL_MODELS_EXHAUSTED: All models are at today's usage limit — try again later (daily quota resets at UTC midnight). Daily use: " + last_err[:200], []
    # Generic fallback: try non-streaming once on first available model
    mdl = available[0] if available else chain[0]
    try:
        resp = await ai_service.client.chat.completions.create(
            model=mdl,
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
            temperature=0.2,
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
        err2 = str(e2)
        if _retry_for_recovery and ("tool_use_failed" in err2 or "Failed to call a function" in err2):
            recovered2 = _recover_from_failed_generation(e2)
            if recovered2:
                return "", recovered2
        if "429" in err2 or "rate_limit" in err2.lower():
            _mark_exhausted(mdl, err2)
            if _is_tpd_error(err2):
                return "ALL_MODELS_EXHAUSTED: All models are at today's usage limit — try again later.", []
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
        # Also detect real environment/toolchains (immediately after inspect) — unless already in history
        should_env = True
        for m in history:
            if "Environment Detection" in str(m.get("content","")) or "Toolchains" in str(m.get("content","")):
                should_env = False
                break
        if should_env:
            yield {"type": "thinking", "content": "Detecting environment…"}
            if is_local and user_id and project_id:
                try:
                    from app.api.bridge import forward_tool_to_bridge
                    env_res = await forward_tool_to_bridge(user_id, project_id, "detect_environment", {}, timeout=15.0)
                except Exception as e:
                    env_res = {"success": False, "output": f"Local bridge error: {e}"}
            else:
                env_res = await execute_tool("detect_environment", {}, mode, workspace=workspace, project_info=project_info)
            yield {"type": "tool_start", "tool": "detect_environment", "input": {}}
            yield {"type": "tool_result", "tool": "detect_environment", "success": env_res["success"], "output": env_res["output"][:3000]}
            messages.append({"role": "assistant", "content": "", "tool_calls": [{"id": "env_0", "type": "function", "function": {"name": "detect_environment", "arguments": "{}"}}]})
            messages.append({"role": "tool", "tool_call_id": "env_0", "content": env_res["output"][:2500]})

    # Main loop — supports multiple tool calls per turn
    changed_files: List[str] = []
    pending_todos: List[Dict[str, Any]] = list(existing_todos or [])
    max_steps = _get_max_steps()
    # Context manager: keep recent history trimmed but preserve important observations
    for step in range(max_steps):
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

        # If we got live content but no tools, it's a final answer — enforce verification before completion
        if not tool_calls:
            if not content or content.startswith("LLM error") or content.startswith("ALL_MODELS_EXHAUSTED"):
                yield {"type": "error", "message": content or "Empty LLM response"}
                break
            # Track if verification was performed in this session
            has_verified = any(
                ("verify_project" in str(m.get("content",""))) or ("verification_result" in str(m.get("content",""))) or ("Build" in str(m.get("content","")) and "PASS" in str(m.get("content","")))
                for m in messages if m.get("role") == "tool"
            ) or any(
                tc.get("name") == "verify_project" for tc in tool_calls
            )
            # Also check changed_files: if we modified files but never verified and still in build mode, nudge to verify
            if mode == "build" and changed_files and not has_verified:
                # inject a synthetic verification reminder as a tool message so next iteration verifies
                # but if the LLM already claims completion, we let it complete and the observability layer will flag unverified
                yield {"type": "thinking", "content": "Final verification pending — ensure build/tests pass before marking complete."}
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
                # Error diagnosis and iterative repair hint
                if not result.get("success"):
                    try:
                        from app.services.error_analyzer import diagnose_output
                        diag = diagnose_output(inp.get("command",""), result.get("output",""), 1)
                        yield {"type": "diagnosis", "category": diag["category"], "summary": diag["summary"], "hint": diag["hint"]}
                        # Append diagnosis to context so LLM can repair
                        messages.append({"role": "tool", "tool_call_id": tc_id, "content": f"Tool {tool} result (success=False):\n{result.get('output','')[:2500]}\n\n[Diagnosis: {diag['category']} — {diag['summary']}. Hint: {diag['hint']}]"})
                    except Exception:
                        messages.append({"role": "tool", "tool_call_id": tc_id, "content": f"Tool {tool} result (success=False):\n{result.get('output','')[:2500]}"})
                else:
                    messages.append({"role": "tool", "tool_call_id": tc_id, "content": f"Tool {tool} result (success=True):\n{result.get('output','')[:2500]}"})
            else:
                yield {"type": "tool_result", "tool": tool, "success": result.get("success", False), "output": result.get("output", "")[:6000]}
                # For verify_project, surface pass/fail clearly
                if tool == "verify_project":
                    status_str = "PASS" if result.get("success") else "FAIL"
                    yield {"type": "verification_result", "success": result.get("success", False), "status": status_str}
                # Feed result back (run_command already handled)
                if tool != "run_command":
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
