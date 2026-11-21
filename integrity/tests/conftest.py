"""Test setup for the integrity module (plan section 10).

The environment variables are set before anything else is imported, the network is blocked for
every test, the project root is on sys.path, and every test gets its own data dir and
INTEGRITY_CONFIG.
"""

import os

os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Unexpected network access in offline tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


@pytest.fixture(autouse=True)
def integrity_env(tmp_path, monkeypatch):
    """Temporary data dir plus an INTEGRITY_CONFIG pointing at it; strips stray INTEGRITY_* variables."""
    for name in list(os.environ):
        if name.startswith("INTEGRITY_"):
            monkeypatch.delenv(name)
    data_dir = tmp_path / "integrity_data"
    (data_dir / "sheets").mkdir(parents=True)
    cfg = tmp_path / "test_config.toml"
    cfg.write_text(f'[paths]\ndata_dir = "{data_dir.as_posix()}"\n', encoding="utf-8")
    monkeypatch.setenv("INTEGRITY_CONFIG", str(cfg))
    return data_dir


@pytest.fixture
def data_dir(integrity_env):
    return integrity_env


@pytest.fixture
def fake_model():
    from integrity.common.llm import FakeModelClient

    return FakeModelClient()
