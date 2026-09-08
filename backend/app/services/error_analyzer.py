"""Error analyzer — classifies failure output into actionable categories."""
import re
from typing import Dict


PATTERNS = [
    (r"compilation failed|compile error|cannot find symbol|error: cannot find|javac.*error|ts\d+|syntax error", "Compilation"),
    (r"module not found|dependency.*not found|could not resolve|unresolved dependency|failed to resolve", "Dependency"),
    (r"npm err!.*404|npm err!.*econn|pip.*could not find|no matching distribution", "Package"),
    (r"type error|typeerror|ts\(\d+\)|mypy.*error", "Type error"),
    (r"syntaxerror|unexpected token|parsing error|unexpected.*char", "Syntax"),
    (r"runtime.*error|exception in thread|traceback|panic|fatal error", "Runtime"),
    (r"config.*error|invalid.*config|misconfigured|unknown.*option", "Configuration"),
    (r"eaddrinuse|port.*in use|address already in use|bind.*failed", "Port"),
    (r"connection refused|database.*unavailable|psql.*error|mongodb.*error|sql.*error", "Database"),
    (r"test.*failed|assertion.*failed|expected.*received|jest.*fail", "Test"),
    (r"build.*failed|failed to build|error.*build", "Build"),
    (r"import.*error|modulenotfounderror|importerror|cannot import", "Import"),
    (r"permission denied|eperm|access denied|operation not permitted", "Permission"),
    (r"toolchain.*not found|command not found|is not recognized|no such file.*mvn|gradle.*not found|flutter.*not found", "Toolchain"),
    (r"timeout|timed out|deadline exceeded", "Timeout"),
]


def classify_error(output: str) -> str:
    low = (output or "").lower()
    for pat, label in PATTERNS:
        if re.search(pat, low, re.I):
            return label
    if "error" in low or "fail" in low:
        return "Build"
    return "Unknown"


def diagnose_output(command: str, output: str, exit_code: int) -> Dict[str, str]:
    """Return structured diagnosis: category, summary, hint."""
    if exit_code == 0:
        return {"category": "Success", "summary": "Command succeeded", "hint": "No repair needed"}
    category = classify_error(output)
    # Short summary: first error line
    lines = (output or "").splitlines()
    error_line = ""
    for line in lines:
        if re.search(r"error|fail|exception|not found|denied", line, re.I):
            error_line = line.strip()[:200]
            break
    if not error_line:
        error_line = lines[-1].strip()[:200] if lines else "Unknown failure"

    hints = {
        "Compilation": "Read compiler output, locate the source file/line, fix syntax/types.",
        "Dependency": "Check package/build file, run install, verify version.",
        "Package": "Verify package name/registry, check network, update lockfile.",
        "Type error": "Fix type annotations / imports, run type checker.",
        "Syntax": "Fix syntax near reported line; read file before editing.",
        "Runtime": "Inspect stack trace, reproduce locally, add missing config.",
        "Configuration": "Validate config file syntax and required keys.",
        "Port": "Kill occupying process or change port.",
        "Database": "Check connection string, ensure DB is running.",
        "Test": "Read failing test output, fix implementation to satisfy assertions.",
        "Build": "Read build log, fix first error, retry.",
        "Import": "Fix import paths, install missing package.",
        "Permission": "Check file permissions or run with appropriate rights.",
        "Toolchain": "Tool not installed — install it or switch to an available toolchain.",
        "Timeout": "Command timed out — check if server is hanging or increase timeout.",
        "Unknown": "Read full output, search relevant files, retry after targeted fix.",
    }
    hint = hints.get(category, hints["Unknown"])
    return {"category": category, "summary": error_line or category, "hint": hint, "command": command}
