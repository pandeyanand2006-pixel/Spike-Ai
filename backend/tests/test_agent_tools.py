import tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.agent_tools import (
    tool_read_file, tool_write_file, tool_edit_file, tool_list_directory,
    tool_search_files, tool_get_file_info, tool_inspect_project,
    tool_detect_environment, tool_verify_project, is_dangerous_command
)

def make_ws():
    tmp = tempfile.TemporaryDirectory()
    ws = Path(tmp.name).resolve()
    # keep reference
    return tmp, ws

def test_file_create_read_edit():
    tmp, ws = make_ws()
    try:
        r = tool_write_file("hello.txt", "hello world", workspace=ws)
        assert r["success"]
        r2 = tool_read_file("hello.txt", workspace=ws)
        assert "hello world" in r2["output"]
        r3 = tool_edit_file("hello.txt", "hello world", "hello spiky", workspace=ws)
        assert r3["success"]
        r4 = tool_read_file("hello.txt", workspace=ws)
        assert "spiky" in r4["output"]
    finally:
        tmp.cleanup()

def test_workspace_confinement():
    tmp, ws = make_ws()
    try:
        r = tool_read_file("../../etc/passwd", workspace=ws)
        assert not r["success"]
        assert "escapes workspace" in r["output"]
        r2 = tool_write_file("../evil.txt", "bad", workspace=ws)
        assert not r2["success"]
    finally:
        tmp.cleanup()

def test_search():
    tmp, ws = make_ws()
    try:
        tool_write_file("a.py", "def foo(): pass", workspace=ws)
        tool_write_file("b.py", "def bar(): pass", workspace=ws)
        r = tool_search_files("foo", workspace=ws)
        assert r["success"]
        assert "foo" in r["output"].lower()
    finally:
        tmp.cleanup()

def test_dangerous_command():
    assert is_dangerous_command("rm -rf /") is True
    assert is_dangerous_command("npm install") is False

def test_detect_environment_tool():
    tmp, ws = make_ws()
    try:
        r = tool_detect_environment(workspace=ws)
        assert r["success"]
        assert "AVAILABLE" in r["output"] or "NOT FOUND" in r["output"]
    finally:
        tmp.cleanup()

def test_verify_project_no_build():
    tmp, ws = make_ws()
    try:
        r = tool_verify_project(workspace=ws, timeout=5)
        assert r["success"] in (True, False)
        assert "output" not in r or isinstance(r["output"], str)
    finally:
        tmp.cleanup()

def test_inspect_project_detects_stack():
    tmp, ws = make_ws()
    try:
        (ws / "package.json").write_text('{"name":"x"}')
        r = tool_inspect_project(workspace=ws)
        assert r["success"]
        assert "Detected stack" in r["output"]
    finally:
        tmp.cleanup()
