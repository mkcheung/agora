import os
import subprocess
import sys

import pytest
from pydantic import BaseModel

from integrity.common import llm


class Out(BaseModel):
    answer: str


def test_prompt_loading_hash_and_render(tmp_path):
    p = tmp_path / "drafter_v1.md"
    p.write_text("Hello {name} {{literal}}", encoding="utf-8")
    prompt = llm.load_prompt(p)
    assert prompt.name == "drafter_v1" and len(prompt.sha256) == 64
    assert prompt.render(name="X") == "Hello X {literal}"
    p.write_text("changed", encoding="utf-8")
    assert llm.load_prompt(p).sha256 != prompt.sha256


def test_fake_client_queue_and_records():
    fake = llm.FakeModelClient([Out(answer="a"), {"answer": "b"}, lambda call: Out(answer=call["user"])])
    assert isinstance(fake, llm.ModelClient)
    assert fake.structured(system="s", user="u1", schema=Out, purpose="p").answer == "a"
    assert fake.structured(system="s", user="u2", schema=Out, purpose="p").answer == "b"
    assert fake.structured(system="s2", user="u3", schema=Out, purpose="q").answer == "u3"
    assert [c["user"] for c in fake.calls] == ["u1", "u2", "u3"] and fake.calls[2]["purpose"] == "q"
    with pytest.raises(AssertionError):
        fake.structured(system="s", user="u", schema=Out, purpose="p")
    fake.queue(ValueError("boom"))
    with pytest.raises(ValueError):
        fake.structured(system="s", user="u", schema=Out, purpose="p")


def test_tracing_off_helper(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    llm.apply_tracing_setting("inherit")
    assert os.environ["LANGSMITH_TRACING"] == "true"
    llm.apply_tracing_setting("off")
    assert os.environ["LANGSMITH_TRACING"] == "false" and os.environ["LANGCHAIN_TRACING_V2"] == "false"


def test_rejects_temperature_heuristic():
    assert llm.rejects_temperature("openai:o3-mini") and llm.rejects_temperature("openai:gpt-5")
    assert not llm.rejects_temperature("openai:gpt-4.1")


def test_import_does_not_load_langchain():
    code = "import sys, integrity.common.llm; sys.exit(1 if any(m.startswith('langchain') for m in sys.modules) else 0)"
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0


class _Runnable:
    def __init__(self, results):
        self.results, self.calls = list(results), 0

    def invoke(self, messages):
        self.calls += 1
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def make_client(results, max_retries=2):
    """LangChainModelClient without the real constructor (no langchain import, no network)."""
    c = llm.LangChainModelClient.__new__(llm.LangChainModelClient)
    c.model_id, c.max_retries, c.backoff_s, c.usage = "fake:m", max_retries, 0.5, []
    c.sleeps = []
    c._sleep = c.sleeps.append
    c._structured_cache = {Out: _Runnable(results)}
    return c


def test_transport_retries_with_backoff_then_succeeds():
    ok = {"raw": None, "parsed": Out(answer="x"), "parsing_error": None}
    c = make_client([ConnectionError("a"), ConnectionError("b"), ok])
    assert c.structured(system="s", user="u", schema=Out, purpose="p").answer == "x"
    assert c.sleeps == [0.5, 1.0]


def test_transport_retries_exhausted():
    c = make_client([ConnectionError("a")] * 3)
    with pytest.raises(llm.ModelCallError):
        c.structured(system="s", user="u", schema=Out, purpose="p")


def test_parse_failure_retried_once_then_raises():
    bad = {"raw": None, "parsed": None, "parsing_error": ValueError("x")}
    ok = {"raw": None, "parsed": {"answer": "y"}, "parsing_error": None}
    assert make_client([bad, ok]).structured(system="s", user="u", schema=Out, purpose="p").answer == "y"
    c = make_client([bad, bad, ok])
    with pytest.raises(llm.ModelOutputError):
        c.structured(system="s", user="u", schema=Out, purpose="p")
    assert c._structured_cache[Out].calls == 2


def test_usage_recorded():
    class Raw:
        usage_metadata = {  # noqa: RUF012
            "input_tokens": 3, "output_tokens": 4}

    c = make_client([{"raw": Raw(), "parsed": Out(answer="x"), "parsing_error": None}])
    c.structured(system="s", user="u", schema=Out, purpose="draft")
    assert c.usage[0]["purpose"] == "draft" and c.usage[0]["input_tokens"] == 3
