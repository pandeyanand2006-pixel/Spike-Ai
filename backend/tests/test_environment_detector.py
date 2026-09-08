import tempfile
from pathlib import Path
import os
import sys

# Ensure backend is on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.environment_detector import detect_installed_tools, format_environment_report, get_tool_availability

def test_detect_installed_tools_real():
    tools = detect_installed_tools()
    assert isinstance(tools, dict)
    # git should be available on most dev machines
    assert "git" in tools
    # python should be available
    assert tools["python"]["available"] in ("true","false")
    # never fabricates: if which is None, available must be false
    import shutil
    for name, info in tools.items():
        if info["available"] == "true":
            assert info["path"] != ""
        else:
            assert info["path"] == ""

def test_format_report_contains_real_markers():
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        # create a marker file
        (ws / "pom.xml").write_text("<project></project>")
        report = format_environment_report(ws)
        assert "Environment Detection" in report
        assert "Toolchains" in report
        assert "pom.xml" in report  # project indicator

def test_local_wrappers():
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        (ws / "mvnw").write_text("# dummy")
        report = format_environment_report(ws)
        assert "mvnw" in report

def test_get_tool_availability():
    # python should be available in this env
    assert get_tool_availability("python") is True or get_tool_availability("python3") is True
    assert get_tool_availability("nonexistent_tool_xyz") is False
