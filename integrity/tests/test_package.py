import ast
import subprocess
import sys
from pathlib import Path

import integrity

PKG = Path(integrity.__file__).parent
ROOT = PKG.parent
MAIN_MODULES = {"ask", "retrieval", "ingest", "parsers", "chunking", "config", "philosophy_query", "tools"}


def imports_of(path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def test_version_constants():
    assert (integrity.SCHEMA_VERSION, integrity.TEXTNORM_VERSION, integrity.CONTRACT_VERSION) == (1, 1, 1)
    assert integrity.MODULE_VERSION


def test_subpackages_importable():
    import integrity.builder
    import integrity.quiz
    import integrity.quiz.grading  # noqa: F401


def test_common_and_cli_never_import_builder_quiz_or_main_program():
    for path in list((PKG / "common").glob("*.py")) + [PKG / "cli.py", PKG / "__main__.py"]:
        for mod in imports_of(path):
            assert not mod.startswith(("integrity.builder", "integrity.quiz")), (path, mod)
            assert mod.split(".")[0] not in MAIN_MODULES, (path, mod)


def test_cli_import_is_light():
    code = ("import sys, integrity.cli; "
            "bad=[m for m in sys.modules if m.startswith(('integrity.builder','integrity.quiz','langchain'))]; "
            "sys.exit(1 if bad else 0)")
    assert subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=False).returncode == 0


def test_main_program_never_imports_integrity():
    for path in ROOT.glob("*.py"):
        assert not any(m.split(".")[0] == "integrity" for m in imports_of(path)), path


def test_only_allowed_files_call_seams_load():
    allowed = {PKG / "builder" / "corpus.py", PKG / "quiz" / "agora.py", PKG / "common" / "seams.py"}
    for path in PKG.rglob("*.py"):
        if path in allowed or "tests" in path.parts:
            continue
        assert "seams.load" not in path.read_text(), path


def test_data_dir_scaffold():
    d = ROOT / "integrity_data"
    assert (d / "sheets" / ".gitkeep").exists()
    lines = (d / ".gitignore").read_text().split()
    assert {"runs/*/raw.jsonl", "runs/*/grades.jsonl", "*.lock"} <= set(lines)
