"""Models that reject the temperature parameter (found in the first live build: Claude 5 returned HTTP 400)."""

import pytest

from integrity.common import llm
from integrity.tests.test_llm import Out, _Runnable, make_client

TEMPERATURE_400 = ("Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', "
                   "'message': '`temperature` is deprecated for this model.'}}")


@pytest.mark.parametrize("model_id", [
    "anthropic:claude-opus-5-5", "anthropic:claude-sonnet-5-5", "anthropic:claude-haiku-5-5",
    "anthropic:claude-fable-5-2", "claude-opus-5-5", "openai:gpt-5", "openai:o3-mini",
])
def test_models_that_reject_temperature(model_id):
    assert llm.rejects_temperature(model_id) is True


@pytest.mark.parametrize("model_id", [
    "openai:gpt-4.1", "anthropic:claude-sonnet-4-5", "anthropic:claude-opus-4-1", "groq:openai/gpt-oss-120b",
])
def test_models_that_accept_temperature(model_id):
    assert llm.rejects_temperature(model_id) is False


def test_is_temperature_error():
    assert llm.is_temperature_error(Exception(TEMPERATURE_400)) is True
    assert llm.is_temperature_error(Exception("Error code: 400 - messages must not be empty")) is False
    assert llm.is_temperature_error(ConnectionError("temperature of the room")) is False  # no 'deprecated' etc.


class _Model:
    def __init__(self, results):
        self.results, self.runnable = results, None

    def with_structured_output(self, schema, method=None, include_raw=False):
        self.runnable = _Runnable(self.results)
        return self.runnable


def test_client_recovers_when_the_provider_refuses_temperature():
    ok = {"raw": None, "parsed": Out(answer="x"), "parsing_error": None}
    c = make_client([Exception(TEMPERATURE_400)])        # first call: the provider refuses temperature
    c._temperature_sent = True
    built = []

    def rebuild_model(model_id, **kwargs):
        built.append(kwargs)
        return _Model([ok])
    c._init_chat_model = rebuild_model
    out = c.structured(system="s", user="u", schema=Out, purpose="attribution")
    assert out.answer == "x"
    assert built == [{}]                    # rebuilt exactly once, without any temperature
    assert c._temperature_sent is False
    assert c.sleeps == []                   # not treated as a transport failure


def test_a_temperature_error_is_not_retried_forever_once_temperature_is_gone():
    c = make_client([Exception(TEMPERATURE_400)] * 3)
    c._temperature_sent = False             # nothing to remove: behaves like any other failing call
    with pytest.raises(llm.ModelCallError):
        c.structured(system="s", user="u", schema=Out, purpose="p")
    assert c._structured_cache[Out].calls == 3
