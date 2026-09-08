"""Environment / toolchain detector — discovers installed binaries and project-local wrappers.

Real detection: uses shutil.which, file existence checks, and subprocess --version.
Never fabricates availability. Mirrors the capability matrix from Cline/OpenHands/Goose.
"""
import shutil
import subprocess
import os
from pathlib import Path
from typing import Dict, List, Optional


# Tools to detect — ordered as in the task spec
TOOL_MATRIX = {
    "java": {"bin": "java", "check": ["java", "-version"]},
    "javac": {"bin": "javac", "check": ["javac", "-version"]},
    "mvn": {"bin": "mvn", "check": ["mvn", "-version"]},
    "gradle": {"bin": "gradle", "check": ["gradle", "--version"]},
    "node": {"bin": "node", "check": ["node", "--version"]},
    "npm": {"bin": "npm", "check": ["npm", "--version"]},
    "pnpm": {"bin": "pnpm", "check": ["pnpm", "--version"]},
    "yarn": {"bin": "yarn", "check": ["yarn", "--version"]},
    "python": {"bin": "python", "check": ["python", "--version"]},
    "python3": {"bin": "python3", "check": ["python3", "--version"]},
    "pip": {"bin": "pip", "check": ["pip", "--version"]},
    "pip3": {"bin": "pip3", "check": ["pip3", "--version"]},
    "uv": {"bin": "uv", "check": ["uv", "--version"]},
    "gcc": {"bin": "gcc", "check": ["gcc", "--version"]},
    "g++": {"bin": "g++", "check": ["g++", "--version"]},
    "clang": {"bin": "clang", "check": ["clang", "--version"]},
    "clang++": {"bin": "clang++", "check": ["clang++", "--version"]},
    "cmake": {"bin": "cmake", "check": ["cmake", "--version"]},
    "make": {"bin": "make", "check": ["make", "--version"]},
    "ninja": {"bin": "ninja", "check": ["ninja", "--version"]},
    "go": {"bin": "go", "check": ["go", "version"]},
    "rustc": {"bin": "rustc", "check": ["rustc", "--version"]},
    "cargo": {"bin": "cargo", "check": ["cargo", "--version"]},
    "dotnet": {"bin": "dotnet", "check": ["dotnet", "--version"]},
    "flutter": {"bin": "flutter", "check": ["flutter", "--version"]},
    "dart": {"bin": "dart", "check": ["dart", "--version"]},
    "adb": {"bin": "adb", "check": ["adb", "--version"]},
    "git": {"bin": "git", "check": ["git", "--version"]},
    "docker": {"bin": "docker", "check": ["docker", "--version"]},
    "docker-compose": {"bin": "docker-compose", "check": ["docker-compose", "--version"]},
}

# Project-local wrappers to inspect inside the workspace
LOCAL_WRAPPERS = ["./mvnw", "./mvnw.cmd", "./gradlew", "./gradlew.bat"]


def _check_binary(check_cmd: List[str]) -> Optional[str]:
    try:
        proc = subprocess.run(check_cmd, capture_output=True, text=True, timeout=5)
        out = (proc.stdout or "") + (proc.stderr or "")
        # first line is version
        line = out.strip().splitlines()[0] if out.strip() else ""
        if proc.returncode == 0:
            return line[:200]
        # some tools return 0 with version in stderr (java -version)
        if line:
            return line[:200]
        return None
    except Exception:
        return None


def detect_installed_tools() -> Dict[str, Dict[str, str]]:
    """Return dict name -> {available, path, version} for every TOOL_MATRIX entry."""
    result: Dict[str, Dict[str, str]] = {}
    for name, spec in TOOL_MATRIX.items():
        bin_name = spec["bin"]
        which = shutil.which(bin_name)
        if which:
            ver = _check_binary(spec["check"])
            result[name] = {
                "available": "true",
                "path": which,
                "version": ver or "unknown",
            }
        else:
            result[name] = {"available": "false", "path": "", "version": ""}
    return result


def detect_local_wrappers(workspace: Path) -> Dict[str, bool]:
    ws = workspace.resolve()
    out: Dict[str, bool] = {}
    for wrapper in LOCAL_WRAPPERS:
        clean = wrapper.lstrip("./")
        exists = (ws / clean).exists()
        # also check with .bat on Windows variant
        out[wrapper] = exists
    return out


def format_environment_report(workspace: Path | None = None) -> str:
    """Human-readable report for injection into LLM context."""
    tools = detect_installed_tools()
    lines: List[str] = []
    lines.append("# Environment Detection (real, not fabricated)")
    lines.append("")
    lines.append("## Toolchains")
    for name in TOOL_MATRIX.keys():
        info = tools[name]
        if info["available"] == "true":
            lines.append(f"- {name}: AVAILABLE ({info['path']}) — {info['version']}")
        else:
            lines.append(f"- {name}: NOT FOUND")
    if workspace:
        lines.append("")
        lines.append(f"## Project-local wrappers ({workspace})")
        wrappers = detect_local_wrappers(workspace)
        for w, present in wrappers.items():
            lines.append(f"- {w}: {'FOUND' if present else 'not found'}")
        # project files hint
        lines.append("")
        lines.append("## Project indicators")
        ws = workspace.resolve()
        indicators = {
            "pom.xml": "Maven",
            "build.gradle": "Gradle (Groovy)",
            "build.gradle.kts": "Gradle (Kotlin)",
            "package.json": "Node.js",
            "requirements.txt": "Python pip",
            "pyproject.toml": "Python (pyproject)",
            "Pipfile": "Pipenv",
            "CMakeLists.txt": "CMake",
            "Makefile": "Make",
            "Cargo.toml": "Rust/Cargo",
            "go.mod": "Go modules",
            "pubspec.yaml": "Flutter/Dart",
            ".csproj": "dotnet",
            "Dockerfile": "Docker",
            "docker-compose.yml": "Docker Compose",
        }
        found_any = False
        for fname, label in indicators.items():
            if fname.startswith("."):
                # glob for csproj
                import fnmatch
                matches = list(ws.glob(f"*{fname}")) + list(ws.glob(f"**/*{fname}"))
                if matches:
                    lines.append(f"- {fname}: present ({label})")
                    found_any = True
            else:
                if (ws / fname).exists():
                    lines.append(f"- {fname}: present ({label})")
                    found_any = True
        if not found_any:
            lines.append("- No standard build files detected (empty or custom layout)")
    lines.append("")
    lines.append("NOTE: Use an AVAILABLE toolchain for project creation/build. If required tool is NOT FOUND, explain the blocker instead of fabricating success.")
    return "\n".join(lines)


def get_tool_availability(tool_name: str) -> bool:
    """Quick check if a single tool is available."""
    spec = TOOL_MATRIX.get(tool_name)
    if not spec:
        return False
    return shutil.which(spec["bin"]) is not None


def tool_detect_environment(workspace: Path | None = None) -> Dict[str, str]:
    """Tool callable — returns the formatted report."""
    from app.config import get_settings
    import logging
    try:
        ws = workspace
        if ws is None:
            from app.services.agent_tools import WORKSPACE
            ws = WORKSPACE
        report = format_environment_report(ws)
        return {"success": True, "output": report}
    except Exception as e:
        logging.getLogger("uvicorn.error").warning(f"detect_environment failed: {e}")
        return {"success": False, "output": f"detect_environment failed: {e}"}
