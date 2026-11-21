"""A rejected API key (HTTP 401/403) is never retried and stops a build with exit 4.

Found in the first live build: the attribution model's key was invalid, every advisory call failed with a 401,
and the build carried on, storing cards that had not had the speaker check.
"""

import pytest

from integrity.builder.build import BuildError, run_build
from integrity.common import llm, storage
from integrity.common.llm import ModelAuthError, ModelCallError
from integrity.common.settings import load_settings
from integrity.tests import builder_helpers as H
from integrity.tests.test_llm import Out, make_client


class FakeStatusError(Exception):
    """Looks like the provider SDKs' HTTP errors (anthropic/openai expose ``status_code``)."""

    def __init__(self, status_code, message="boom"):
        super().__init__(message)
        self.status_code = status_code


ANTHROPIC_401 = ("Error code: 401 - {'type': 'error', 'error': {'type': 'authentication_error', "
                 "'message': 'invalid x-api-key'}}")


@pytest.mark.parametrize("exc", [
    FakeStatusError(401), FakeStatusError(403), Exception(ANTHROPIC_401),
    Exception("Incorrect API key provided: sk-xxxx"), Exception("invalid_api_key"),
])
def test_is_auth_error_true(exc):
    assert llm.is_auth_error(exc) is True


@pytest.mark.parametrize("exc", [FakeStatusError(500), FakeStatusError(429, "rate limited"),
                                 ConnectionError("reset"), Exception("timeout")])
def test_is_auth_error_false(exc):
    assert llm.is_auth_error(exc) is False


def test_client_does_not_retry_a_rejected_key():
    c = make_client([FakeStatusError(401, ANTHROPIC_401)] * 3)
    with pytest.raises(ModelAuthError):
        c.structured(system="s", user="u", schema=Out, purpose="attribution")
    assert c._structured_cache[Out].calls == 1 and c.sleeps == []  # one call, no backoff sleeps


def test_other_transport_errors_are_still_retried():
    c = make_client([FakeStatusError(500)] * 3)
    with pytest.raises(ModelCallError) as e:
        c.structured(system="s", user="u", schema=Out, purpose="p")
    assert not isinstance(e.value, ModelAuthError) and c._structured_cache[Out].calls == 3


def test_auth_error_is_a_model_call_error():
    assert issubclass(ModelAuthError, ModelCallError)


def test_build_stops_with_exit_4_when_the_attribution_key_is_rejected(data_dir):
    settings = load_settings()
    advisor = H.ScriptedClient(lambda c, i: ModelAuthError("attribution: the provider rejected the API key"))
    drafter = H.ScriptedClient(H.good_draft)
    with pytest.raises(BuildError) as e:
        run_build(settings, count=4, seed=7, corpus=H.fake_corpus(30), drafter_client=drafter,
                  attribution_client=advisor)
    assert e.value.exit_code == 4 and "attribution" in str(e.value)
    assert len(advisor.calls) == 1  # stopped at the first rejection, not after every slot
    # no card was stored without the speaker check
    batch_dirs = list((data_dir / "drafts").iterdir())
    assert len(batch_dirs) == 1
    assert storage.read_jsonl(batch_dirs[0] / "cards.jsonl") == []
    assert storage.read_json(batch_dirs[0] / "batch.json")["status"] == "aborted"


def test_build_stops_with_exit_4_when_the_drafting_key_is_rejected(data_dir):
    settings = load_settings()
    drafter = H.ScriptedClient(lambda c, i: ModelAuthError("draft: the provider rejected the API key"))
    advisor = H.ScriptedClient(H.advisory_ok)
    with pytest.raises(BuildError) as e:
        run_build(settings, count=4, seed=7, corpus=H.fake_corpus(30), drafter_client=drafter,
                  attribution_client=advisor)
    assert e.value.exit_code == 4 and "drafting" in str(e.value)
    assert len(drafter.calls) == 1 and advisor.calls == []


def test_a_transient_advisory_failure_is_still_only_a_warning(data_dir):
    """Only a rejected key is fatal; an outage of the advisory model keeps the old behaviour."""
    settings = load_settings()
    advisor = H.ScriptedClient(lambda c, i: ModelCallError("advisory down") if i == 0 else H.advisory_ok(c, i))
    s = run_build(settings, count=2, seed=7, corpus=H.fake_corpus(30),
                  drafter_client=H.ScriptedClient(H.good_draft), attribution_client=advisor)
    assert s.filled == 2 and any("advisory failed" in w for w in s.warnings)
