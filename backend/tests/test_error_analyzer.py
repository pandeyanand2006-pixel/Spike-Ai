import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.error_analyzer import classify_error, diagnose_output

def test_classify_compilation():
    assert classify_error("error: cannot find symbol Foo") == "Compilation"
    assert classify_error("SyntaxError: unexpected token") == "Syntax"

def test_classify_dependency():
    assert classify_error("Could not resolve dependency com.example:foo") == "Dependency"

def test_classify_toolchain():
    assert classify_error("mvn: command not found") == "Toolchain"
    assert classify_error("'flutter' is not recognized") == "Toolchain"

def test_diagnose_output():
    d = diagnose_output("mvn test", "ERROR Compilation failure\ncannot find symbol", 1)
    assert d["category"] == "Compilation"
    assert "hint" in d
    assert d["command"] == "mvn test"

def test_success():
    d = diagnose_output("npm test", "PASS", 0)
    assert d["category"] == "Success"
