import os
import sys

import pytest

from integrity.common import seams


@pytest.fixture
def fake_root(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "fake_main_mod.py").write_text(
        "import os\nNS = os.environ.get('AGORA_NAMESPACE')\n\ndef answer(q):\n    return q\n"
    )
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.delenv("AGORA_NAMESPACE", raising=False)
    yield root
    sys.modules.pop("fake_main_mod", None)


def test_parse_spec():
    assert seams.parse_spec("a.b:c") == ("a.b", "c")
    for bad in ("nocolon", ":x", "x:"):
        with pytest.raises(seams.SeamError):
            seams.parse_spec(bad)


def test_load_puts_root_first_and_imports_lazily(fake_root):
    assert "fake_main_mod" not in sys.modules
    fn = seams.load("fake_main_mod:answer", project_root=fake_root)
    assert fn("q") == "q"
    assert sys.path[0] == str(fake_root.resolve())


def test_namespace_applied_before_import(fake_root):
    seams.load("fake_main_mod:answer", project_root=fake_root, namespace="ns-test")
    assert os.environ["AGORA_NAMESPACE"] == "ns-test"
    assert sys.modules["fake_main_mod"].NS == "ns-test"


def test_errors(fake_root):
    with pytest.raises(seams.SeamError, match="cannot import"):
        seams.load("no_such_mod_xyz:f", project_root=fake_root)
    with pytest.raises(seams.SeamError, match="no attribute"):
        seams.load("fake_main_mod:missing", project_root=fake_root)
