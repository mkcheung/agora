"""build orchestration, batch files, the API and the CLI handlers (fake models, fake corpus)."""

import re
import subprocess
import sys
import types

import pytest

from integrity import cli
from integrity.builder import api
from integrity.builder.build import BuildError, run_build
from integrity.common import storage
from integrity.common.llm import ModelCallError, ModelOutputError
from integrity.common.schema import Card
from integrity.common.settings import load_settings
from integrity.tests import builder_helpers as H


def never(call, i):
    raise AssertionError("no model call is allowed here")


@pytest.fixture
def settings():
    return load_settings()


@pytest.fixture
def corpus():
    return H.fake_corpus(30)


@pytest.fixture
def fake_provider(monkeypatch):
    mod = types.ModuleType("builder_fake_provider")
    mod.provide = lambda sources=None: H.fake_chunks(30)
    monkeypatch.setitem(sys.modules, "builder_fake_provider", mod)
    monkeypatch.setenv("INTEGRITY_SEAMS__CORPUS_PROVIDER", "builder_fake_provider:provide")


def build(settings, corpus, drafter, advisor=None, **kw):
    kw.setdefault("count", 8)
    kw.setdefault("seed", 7)
    return run_build(
        settings, drafter_client=drafter, attribution_client=advisor or H.ScriptedClient(H.advisory_ok),
        corpus=corpus, **kw,
    )


def test_dry_run_plans_renders_prompts_and_makes_no_model_call_or_files(settings, corpus, data_dir):
    client = H.ScriptedClient(never)
    s1 = run_build(settings, count=8, seed=7, dry_run=True, corpus=corpus, drafter_client=client,
                   attribution_client=client)
    s2 = run_build(settings, count=8, seed=7, dry_run=True, corpus=corpus)
    assert client.calls == [] and s1.plan == s2.plan and len(s1.plan) == 8 and len(s1.prompts) == 8
    assert "PARAGRAPH:" in s1.prompts[0]["user"] and "THE QUESTION" in s1.prompts[0]["system"]
    assert not (data_dir / "drafts").exists()
    assert "no files written" in s1.format()


def test_full_build_writes_batch_dir_with_cards_discards_and_provenance(settings, corpus, data_dir):
    drafter = H.ScriptedClient(lambda c, i: H.good_draft(c, i))
    s = build(settings, corpus, drafter)
    assert s.filled == 8 and s.unfilled == [] and s.discarded == 0
    bdir = data_dir / "drafts" / s.batch_id
    assert re.fullmatch(r"b-\d{8}-\d{6}-s7", s.batch_id)
    batch = storage.read_json(bdir / "batch.json")
    assert batch["seed"] == 7 and batch["status"] == "complete" and len(batch["slots"]) == 8
    assert batch["corpus_version"] == "epub-v1-test" and batch["config"]["build"]["default_count"] == 24
    assert set(batch["prompt_hashes"]) == {"drafter_v1", "attribution_v1"}
    rows = storage.read_jsonl(bdir / "cards.jsonl")
    assert len(rows) == 8 and storage.read_jsonl(bdir / "discarded.jsonl") == []
    card = Card.model_validate(rows[0])
    assert card.review.status == "pending" and card.type == "passage" and card.expected_behavior == "answer"
    p = card.provenance
    assert p.batch_id == s.batch_id and p.seed == 7 and p.attempt == 1 and p.drafter_prompt == "drafter_v1"
    assert p.attribution_advice and p.attribution_advice[0].evidence_verified is True
    a = card.anchor
    assert a.text[card.key_points[0].span[0]:card.key_points[0].span[1]] == card.key_points[0].quote
    assert a.skeleton_sha256 and a.source_sha256 and a.corpus_version == "epub-v1-test" and a.chunks
    assert card.card_id.startswith("c-") and "attribution_advice" not in card.flags
    assert not list(bdir.glob(".*.tmp"))  # atomic writes leave no temp files


def test_top_up_redraws_within_the_same_bin_and_logs_discards(settings, corpus, data_dir):
    def fn(call, i):
        d = H.good_draft(call, i)
        if i % 2 == 0:  # every first attempt is bad: a quote that is not in the paragraph
            d["key_points"][0]["quote"] = "completely invented words that are not there"
        return d

    s = build(settings, corpus, H.ScriptedClient(fn), count=4)
    assert s.filled == 4 and s.discarded == 4 and s.discarded_by_reason == {"HC4": 4}
    bdir = data_dir / "drafts" / s.batch_id
    batch = storage.read_json(bdir / "batch.json")
    assert batch["slots"]
    for slot in batch["slots"]:
        tried = slot["candidates_tried"]
        assert [t["result"] for t in tried] == ["discarded", "accepted"]
        assert tried[0]["block_id"] != tried[1]["block_id"]
    d = storage.read_jsonl(bdir / "discarded.jsonl")[0]
    assert d["failed_checks"][0]["check"] == "HC4" and d["raw_output"]["status"] == "ok" and d["attempt"] == 1
    cards = storage.read_jsonl(bdir / "cards.jsonl")
    assert all(c["provenance"]["attempt"] == 2 for c in cards)


def test_unfilled_slots_after_max_attempts_and_no_move_to_other_bins(settings, corpus):
    drafter = H.ScriptedClient(lambda c, i: {**H.good_draft(c, i), "status": "unsuitable",
                                             "unsuitable_reason": "poor", "question": "", "key_points": []})
    s = build(settings, corpus, drafter, count=4)
    assert s.filled == 0 and len(s.unfilled) == 4 and s.discarded_by_reason == {"HC1": 12}
    assert len(drafter.calls) == 12  # max_attempts_per_slot (3) per slot, nothing more
    s2 = build(load_settings({"build": {"max_attempts_per_slot": 1}}), corpus, H.ScriptedClient(
        lambda c, i: {**H.good_draft(c, i), "status": "unsuitable"}), count=4)
    assert s2.discarded == 4
    assert "unfilled" in s.format()


def test_unsuitable_and_model_output_errors_are_discarded_not_fatal(settings, corpus):
    seq = [ModelOutputError("bad json"), None]

    def fn(call, i):
        if i == 0:
            return ModelOutputError("bad json")
        return H.good_draft(call, i)

    s = build(settings, corpus, H.ScriptedClient(fn), count=2)
    assert s.filled == 2 and s.discarded_by_reason == {"model_output_error": 1} and seq


def test_consecutive_model_call_failures_abort_with_exit_5_and_keep_the_batch(settings, corpus, data_dir):
    drafter = H.ScriptedClient(lambda c, i: ModelCallError("boom"))
    with pytest.raises(BuildError) as e:
        build(settings, corpus, drafter, count=4)
    assert e.value.exit_code == 5
    batch = storage.read_json(next((data_dir / "drafts").iterdir()) / "batch.json")
    assert batch["status"] == "aborted"


def test_missing_credentials_exit_4(settings, corpus, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(BuildError) as e:
        run_build(settings, count=2, seed=1, corpus=corpus)
    assert e.value.exit_code == 4 and "OPENAI_API_KEY" in str(e.value)


def test_attribution_advisory_flags_unverified_and_failures_never_discard(settings, corpus):
    def adv(call, i):
        ids = re.findall(r"^(kp\d+):", call["user"], re.MULTILINE)
        if i == 0:
            return ModelCallError("advisory down")
        return {"items": [{"key_point_id": k, "speaker": "reported_view", "explanation": "e",
                           "evidence": "not in the text at all"} for k in ids]}

    s = build(settings, corpus, H.ScriptedClient(H.good_draft), H.ScriptedClient(adv), count=2)
    assert s.filled == 2 and any("advisory failed" in w for w in s.warnings)
    assert s.flags.get("attribution_advice") == 1


def test_advisory_can_be_switched_off(corpus):
    st = load_settings({"build": {"attribution_advisory": False}})
    adv = H.ScriptedClient(never)
    s = run_build(st, count=2, seed=1, corpus=corpus, drafter_client=H.ScriptedClient(H.good_draft),
                  attribution_client=adv)
    assert s.filled == 2 and adv.calls == []


def test_false_premise_path(settings, corpus, data_dir):
    drafter = H.ScriptedClient(lambda c, i: H.good_draft(c, i, premise="The author says the opposite."))
    s = build(settings, corpus, drafter, count=0, false_premise=4)
    assert s.filled == 4 and all("#fp" in r["slot"] for r in s.plan)
    assert all("false-premise" in c["system"] and "THE PREMISE" in c["system"] for c in drafter.calls)
    assert all(c["schema"].__name__ == "FalsePremiseDraft" for c in drafter.calls)
    cards = [Card.model_validate(r) for r in storage.read_jsonl(data_dir / "drafts" / s.batch_id / "cards.jsonl")]
    assert {c.type for c in cards} == {"false_premise"} and {c.expected_behavior for c in cards} == {"correct_premise"}
    assert all(c.premise == "The author says the opposite." for c in cards)
    assert cards[0].provenance.drafter_prompt == "drafter_false_premise_v1"
    # a draft without a premise is discarded by HC2
    s2 = build(settings, corpus, H.ScriptedClient(lambda c, i: H.good_draft(c, i, premise="")), count=0,
               false_premise=2, seed=8)
    assert s2.filled == 0 and s2.discarded_by_reason == {"HC2": 6}


def test_mixed_passage_and_false_premise_slots_do_not_share_paragraphs(settings, corpus):
    s = build(settings, corpus, H.ScriptedClient(lambda c, i: H.good_draft(
        c, i, premise="P." if "THE PREMISE" in c["system"] else None)), count=8, false_premise=4)
    assert s.filled == 12
    blocks = [r["block_id"] for r in s.plan]
    assert len(blocks) == len(set(blocks))


def test_second_build_skips_paragraphs_of_pending_drafts(settings, corpus, data_dir):
    a = build(settings, corpus, H.ScriptedClient(H.good_draft), count=8)
    used = {r["anchor"]["block_id"] for r in storage.read_jsonl(data_dir / "drafts" / a.batch_id / "cards.jsonl")}
    b = run_build(settings, count=8, seed=7, dry_run=True, corpus=corpus)
    assert used.isdisjoint({r["block_id"] for r in b.plan})


def test_authors_and_source_options(settings, corpus):
    s = run_build(settings, count=4, seed=1, dry_run=True, corpus=corpus, authors=["locke"])
    assert {r["author"] for r in s.plan} == {"John Locke"}
    with pytest.raises(BuildError) as e:
        run_build(settings, count=4, seed=1, dry_run=True, corpus=corpus, authors=["Plato"])
    assert e.value.exit_code == 1


def test_api_build_defaults_and_signature(fake_provider, data_dir):
    import inspect

    assert list(inspect.signature(api.build).parameters)[:6] == [
        "count", "false_premise", "sources", "authors", "seed", "dry_run"]
    s = api.build(seed=3, dry_run=True)
    # defaults: 24 passage slots plus 6 false-premise slots (Phase A7)
    assert len(s.plan) == 30 and s.dry_run
    assert sum(1 for slot in s.plan if slot["kind"] == "false_premise") == 6


def test_cli_corpus_and_build_dry_run(fake_provider, capsys):
    assert cli.main(["corpus"]) == 0
    out = capsys.readouterr().out
    assert "AUTHOR" in out and "STRATA" in out and "John Locke" in out and "EXCLUSIONS BY REASON" in out
    assert cli.main(["corpus", "--excluded", "type", "--show", "2"]) == 0
    assert "EL-type" in capsys.readouterr().out
    assert cli.main(["corpus", "--excluded", "nonsense"]) == 1
    capsys.readouterr()
    assert cli.main(["build", "--dry-run", "--seed", "7", "--count", "6", "--false-premise", "0"]) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "6 slots planned" in out and "rendered prompt" in out
    assert cli.main(["build", "--dry-run", "--author", "Nobody"]) == 1


def test_cli_build_without_credentials_exits_4(fake_provider, monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert cli.main(["build", "--count", "2", "--seed", "1"]) == 4


def test_builder_api_does_not_import_quiz():
    code = ("import sys, integrity.builder.api, integrity.builder.handlers;"
            "assert not [m for m in sys.modules if m.startswith('integrity.quiz')], 'quiz imported'")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
