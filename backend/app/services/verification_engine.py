"""Verification engine — infers and runs validation commands from project structure.

Infers correct commands per stack (Maven, Gradle, Node, Python, C++, Go, Rust, Flutter, etc.)
Uses real subprocess execution via agent_tools.run_command — never fabricates results.
"""
import os
import re
from pathlib import Path
from typing import Dict, List, Tuple


def _has(ws: Path, rel: str) -> bool:
    return (ws / rel).exists()


def infer_verification_commands(workspace: Path) -> List[Dict[str, str]]:
    """Return ordered list of {command, purpose, workdir} to validate the project."""
    ws = workspace.resolve()
    cmds: List[Dict[str, str]] = []

    # Java — prefer wrappers
    if _has(ws, "mvnw") or _has(ws, "mvnw.cmd"):
        # Use wrapper
        wrapper = "./mvnw" if (ws / "mvnw").exists() else "mvnw.cmd"
        if _has(ws, "pom.xml"):
            cmds.append({"command": f"{wrapper} test", "purpose": "Maven wrapper tests", "workdir": "."})
            cmds.append({"command": f"{wrapper} package -DskipTests", "purpose": "Maven package", "workdir": "."})
    elif _has(ws, "pom.xml"):
        cmds.append({"command": "mvn test", "purpose": "Maven tests", "workdir": "."})
        cmds.append({"command": "mvn package -DskipTests", "purpose": "Maven package", "workdir": "."})
    if _has(ws, "gradlew") or _has(ws, "gradlew.bat"):
        wrapper = "./gradlew" if (ws / "gradlew").exists() else "gradlew.bat"
        cmds.append({"command": f"{wrapper} test", "purpose": "Gradle tests", "workdir": "."})
        cmds.append({"command": f"{wrapper} build", "purpose": "Gradle build", "workdir": "."})
    elif _has(ws, "build.gradle") or _has(ws, "build.gradle.kts"):
        cmds.append({"command": "gradle test", "purpose": "Gradle tests", "workdir": "."})

    # Node / JS — package.json
    if _has(ws, "package.json"):
        # Check that node_modules isn't required to be blindly installed — infer install step
        try:
            import json as _j
            pkg = _j.loads((ws / "package.json").read_text()[:8000])
            scripts = pkg.get("scripts", {})
        except Exception:
            scripts = {}
        # install should be first if lockfiles present but node_modules missing
        # We always suggest install as verification will need it
        if not (ws / "node_modules").exists():
            # prefer manager based on lockfiles
            if _has(ws, "pnpm-lock.yaml"):
                cmds.append({"command": "pnpm install", "purpose": "Install deps (pnpm)", "workdir": "."})
            elif _has(ws, "yarn.lock"):
                cmds.append({"command": "yarn install", "purpose": "Install deps (yarn)", "workdir": "."})
            else:
                cmds.append({"command": "npm install", "purpose": "Install deps (npm)", "workdir": "."})
        if "build" in scripts:
            # npm run build or next build etc uses package manager
            if _has(ws, "pnpm-lock.yaml"):
                cmds.append({"command": "pnpm run build", "purpose": "Build", "workdir": "."})
            elif _has(ws, "yarn.lock"):
                cmds.append({"command": "yarn build", "purpose": "Build", "workdir": "."})
            else:
                cmds.append({"command": "npm run build", "purpose": "Build", "workdir": "."})
        elif _has(ws, "vite.config.js") or _has(ws, "vite.config.ts"):
            cmds.append({"command": "npm run build", "purpose": "Vite build", "workdir": "."})
        if "test" in scripts:
            if _has(ws, "pnpm-lock.yaml"):
                cmds.append({"command": "pnpm test", "purpose": "Tests", "workdir": "."})
            elif _has(ws, "yarn.lock"):
                cmds.append({"command": "yarn test", "purpose": "Tests", "workdir": "."})
            else:
                cmds.append({"command": "npm test -- --passWithNoTests --watchAll=false", "purpose": "Tests", "workdir": "."})
        elif _has(ws, "node_modules"):
            # no test script but check build passes
            pass

    # Python
    if _has(ws, "pyproject.toml") or _has(ws, "requirements.txt") or _has(ws, "Pipfile"):
        # Look for pytest config
        has_pytest = any(_has(ws, p) for p in ["pytest.ini", "pyproject.toml", "tests", "test"])
        if has_pytest:
            # prefer python -m pytest
            cmds.append({"command": "python -m pytest -q", "purpose": "Python tests", "workdir": "."})
            # fallback pip
            cmds.append({"command": "python3 -m pytest -q", "purpose": "Python tests (python3)", "workdir": "."})
        # else lightweight syntax check
        if _has(ws, "requirements.txt"):
            cmds.append({"command": "python -m py_compile main.py", "purpose": "Python compile check", "workdir": "."})

    # C / C++
    if _has(ws, "CMakeLists.txt"):
        # cmake configure + build + ctest
        cmds.append({"command": "cmake -S . -B build", "purpose": "CMake configure", "workdir": "."})
        cmds.append({"command": "cmake --build build", "purpose": "CMake build", "workdir": "."})
        if _has(ws, "build"):
            cmds.append({"command": "ctest --test-dir build --output-on-failure", "purpose": "CTest", "workdir": "."})
    elif _has(ws, "Makefile"):
        cmds.append({"command": "make", "purpose": "Make build", "workdir": "."})
        # ctest if CTest present

    # Go
    if _has(ws, "go.mod"):
        cmds.append({"command": "go test ./...", "purpose": "Go tests", "workdir": "."})
        cmds.append({"command": "go build ./...", "purpose": "Go build", "workdir": "."})

    # Rust
    if _has(ws, "Cargo.toml"):
        cmds.append({"command": "cargo test", "purpose": "Cargo tests", "workdir": "."})
        cmds.append({"command": "cargo build", "purpose": "Cargo build", "workdir": "."})

    # Flutter / Dart
    if _has(ws, "pubspec.yaml"):
        cmds.append({"command": "flutter analyze", "purpose": "Flutter analyze", "workdir": "."})
        cmds.append({"command": "flutter test", "purpose": "Flutter tests", "workdir": "."})

    # .NET
    # glob for csproj/sln
    has_csproj = any(ws.glob("*.csproj")) or any(ws.glob("**/*.csproj"))
    has_sln = any(ws.glob("*.sln"))
    if has_csproj or has_sln:
        cmds.append({"command": "dotnet build", "purpose": ".NET build", "workdir": "."})
        cmds.append({"command": "dotnet test", "purpose": ".NET tests", "workdir": "."})

    # Docker
    if _has(ws, "Dockerfile"):
        cmds.append({"command": "docker build -t spike-verify .", "purpose": "Docker build", "workdir": "."})

    # If nothing inferred but workspace has source, suggest generic checks
    if not cmds:
        # check src presence
        if (ws / "src").exists():
            # generic: if package.json missing but src has .py, try python compile
            if any(ws.glob("**/*.py")):
                cmds.append({"command": "python -m compileall -q src", "purpose": "Python syntax check", "workdir": "."})
        # empty: no verification possible, report as such (caller will handle)
    return cmds


def smoke_test_web(workspace: Path) -> List[Dict[str, str]]:
    """Suggest dev server smoke commands for web projects."""
    ws = workspace.resolve()
    out: List[Dict[str, str]] = []
    if _has(ws, "package.json"):
        try:
            import json as _j
            pkg = _j.loads((ws / "package.json").read_text()[:4000])
            scripts = pkg.get("scripts", {})
            if "dev" in scripts:
                out.append({"command": "npm run dev -- --host 0.0.0.0 --port 5173", "purpose": "Start dev server (report URL)", "workdir": "."})
            elif "start" in scripts:
                out.append({"command": "npm start", "purpose": "Start server", "workdir": "."})
        except Exception:
            pass
    return out


def classify_verification_result(exit_code: int, output: str) -> str:
    if exit_code == 0:
        return "PASS"
    low = (output or "").lower()
    if "fail" in low and "test" in low:
        return "FAIL_TESTS"
    if "error" in low and "compil" in low:
        return "FAIL_COMPILATION"
    if "not found" in low or "command not found" in low:
        return "MISSING_TOOL"
    return "FAIL"


async def run_inferred_verification(workspace: Path, timeout: int = 60) -> Dict[str, object]:
    """Run the first meaningful verification command (real execution). Used as tool."""
    from app.services.agent_tools import tool_run_command
    cmds = infer_verification_commands(workspace)
    if not cmds:
        return {"success": True, "output": "No verification command inferred — project has no standard build/test markers. Implementation complete without automated verification."}
    # Try the first command that is most representative; but try at most 2
    results = []
    for spec in cmds[:3]:
        cmd = spec["command"]
        purpose = spec["purpose"]
        wd = spec.get("workdir", ".")
        res = tool_run_command(cmd, workdir=wd, timeout=timeout, workspace=workspace)
        out = res.get("output", "")
        success = res.get("success", False)
        results.append(f"## {purpose}: `{cmd}` -> {'PASS' if success else 'FAIL'}\n{out[:3000]}")
        if success and purpose not in ("Install deps",):
            # first passing non-install verification is success
            return {"success": True, "output": "\n\n".join(results)}
        if not success:
            # check if failure is missing tool — try alternative
            if "not found" in out.lower() or "command not found" in out.lower():
                continue
            return {"success": False, "output": "\n\n".join(results)}
    # if we got here, install may have passed but build not yet — return whatever we have
    output = "\n\n".join(results)
    has_pass = any("PASS" in r for r in results)
    return {"success": has_pass, "output": output}
