import tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.verification_engine import infer_verification_commands

def test_infer_maven():
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        (ws / "pom.xml").write_text("<project></project>")
        cmds = infer_verification_commands(ws)
        assert any("mvn" in c["command"] for c in cmds)

def test_infer_node():
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        (ws / "package.json").write_text('{"name":"t","scripts":{"build":"vite build"}}')
        cmds = infer_verification_commands(ws)
        assert any("install" in c["command"] for c in cmds)

def test_infer_python():
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        (ws / "requirements.txt").write_text("fastapi\n")
        (ws / "tests").mkdir()
        cmds = infer_verification_commands(ws)
        assert any("pytest" in c["command"] for c in cmds)

def test_infer_cmake():
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        (ws / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.10)")
        cmds = infer_verification_commands(ws)
        assert any("cmake" in c["command"] for c in cmds)

def test_infer_go():
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        (ws / "go.mod").write_text("module test")
        cmds = infer_verification_commands(ws)
        assert any("go test" in c["command"] for c in cmds)

def test_infer_empty():
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        cmds = infer_verification_commands(ws)
        assert isinstance(cmds, list)
