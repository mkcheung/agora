"""B1: preflight and the Agora adapter."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from integrity.common import sheets as sh
from integrity.common import storage
from integrity.common.settings import load_settings
from integrity.quiz import agora
from integrity.quiz import preflight as pf
from integrity.tests import quiz_fake_agora as fa
from integrity.tests import quiz_fixtures as qf

ROOT = Path(__file__).resolve().parents[2]
GOOD = "integrity.tests.quiz_fake_agora:good_agora"
KEYS = {"OPENAI_API_KEY": "k"}


@pytest.fixture
def env(data_dir):
    qf.write_sheet(data_dir)
    fa.register()
    return data_dir


def pre(**kw):
    kw.setdefault("env", KEYS)
    kw.setdefault("agora", GOOD)
    settings = kw.pop("settings", None) or qf.settings_for()
    r = pf.run_preflight(settings, **kw)
    r.release()
    return r


def test_no_sheet_exits_2_with_exact_message(data_dir):
    r = pre()
    assert r.exit_code == 2
    assert r.message == pf.P1_MESSAGE
    assert r.message.splitlines()[0] == "integrity quiz: no published answer sheet found in integrity_data/sheets/."
    assert r.message.splitlines()[-1] == "  python -m integrity publish    # publish answer sheet v001"


def test_empty_data_dir_cli_subprocess_exits_2(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text(f'[paths]\ndata_dir = "{(tmp_path / "d").as_posix()}"\n')
    r = subprocess.run([sys.executable, "-m", "integrity", "quiz"], cwd=ROOT, capture_output=True, text=True, check=False,
                       env={**os.environ, "INTEGRITY_CONFIG": str(cfg)})
    assert r.returncode == 2
    assert pf.P1_MESSAGE in r.stderr


def test_missing_specific_sheet_exits_2(env):
    assert pre(sheet="v007").exit_code == 2


def test_tampered_sheet_exits_2(env):
    p = sh.sheet_path(env, "v001")
    p.chmod(0o644)
    p.write_text(p.read_text().replace("every man has", "every men has", 1))
    r = pre()
    assert r.exit_code == 2 and "content_sha256" in r.message


def test_empty_sheet_exits_2(data_dir):
    qf.write_sheet(data_dir, cards=[])
    assert pre().exit_code == 2


def test_min_cards_after_filters(env):
    s = qf.settings_for(min_cards=4)
    assert pre(settings=s).exit_code == 0  # 4 scorable non-holdout cards
    assert pre(settings=s, authors=["Locke"]).exit_code == 2
    assert pre(settings=qf.settings_for(min_cards=1), cards=["c-nope"]).exit_code == 1


def test_filters_and_limit(env):
    r = pf.run_preflight(qf.settings_for(), agora=GOOD, env=KEYS, authors=["john locke"], limit=1)
    r.release()
    assert len(r.cards) == 1 and r.cards[0].anchor.author == "John Locke"


@pytest.mark.parametrize("spec", ["no_such_module_xyz:f", "integrity.tests.quiz_fake_agora:missing",
                                  "integrity.tests.quiz_fake_agora:not_callable", "nocolon"])
def test_bad_entrypoint_exits_3_with_contract_summary(env, spec):
    r = pre(agora=spec)
    assert r.exit_code == 3
    assert "Agora entrypoint contract" in r.message and "citations" in r.message


def test_missing_judge_key_exits_4_but_mechanical_only_passes(env):
    assert pre(env={}).exit_code == 4
    assert pre(env={}, mechanical_only=True).exit_code == 0


def test_same_family_judge_warns_and_strict_exits_4(env):
    s = load_settings({"models": {"judge": "anthropic:claude-opus-5-5"}, "quiz": {"min_cards": 1}})
    r = pre(settings=s, env={"ANTHROPIC_API_KEY": "k"})
    assert r.exit_code == 0 and r.warnings and "same provider family" in r.warnings[0]
    assert pre(settings=s, env={"ANTHROPIC_API_KEY": "k"}, strict=True).exit_code == 4
    # a different family is silent
    assert pre().warnings == []


def test_run_lock_blocks_second_run(env):
    first = pf.run_preflight(qf.settings_for(), agora=GOOD, env=KEYS)
    assert first.exit_code == 0
    second = pf.run_preflight(qf.settings_for(), agora=GOOD, env=KEYS)
    assert second.exit_code == 4 and "held by" in second.message
    first.release()
    third = pf.run_preflight(qf.settings_for(), agora=GOOD, env=KEYS)
    assert third.exit_code == 0
    third.release()


def test_stale_lock_is_taken_over(env):
    storage.runs_lock_path(env).parent.mkdir(parents=True, exist_ok=True)
    storage.runs_lock_path(env).write_text("999999999\n")
    assert pre().exit_code == 0


def test_git_state_recorded_or_tolerated(env, tmp_path):
    r = pf.run_preflight(qf.settings_for(), agora=GOOD, env=KEYS)
    r.release()
    assert r.git_commit is None or len(r.git_commit) == 40
    assert pf.git_state(tmp_path) == (None, None)


def test_namespace_override_applied_before_import(env, monkeypatch):
    monkeypatch.setenv("AGORA_NAMESPACE", "original")
    sys.modules.pop("integrity.tests.quiz_fake_agora_ns", None)
    r = pre(agora="integrity.tests.quiz_fake_agora_ns:answer_question", namespace="ns-override", mechanical_only=True)
    assert r.exit_code == 0
    mod = sys.modules["integrity.tests.quiz_fake_agora_ns"]
    assert mod.NAMESPACE_AT_IMPORT == "ns-override"
    sys.modules.pop("integrity.tests.quiz_fake_agora_ns")


# --------------------------------------------------------------------------- contract fixtures

REAL_ASK_SHAPE = {
    "answer": "Locke says labour makes property (John Locke, Second Treatise of Government, Book II, Chapter 5, §27).",
    "citations": [{"author": "John Locke", "work": "Second Treatise of Government", "chapter": 5, "section": 27,
                   "quote": "every man has a property in his own person", "passage_id": "pg7370:main:abc:c0",
                   "locator": "Book II, Chapter 5, §27"}],
    "retrieved": [{"rank": 1, "author": "John Locke", "work": "Second Treatise of Government", "locator": "Book II, Chapter 5, §27",
                   "passage_id": "pg7370:main:abc:c0", "block_id": "pg7370:main:abc", "work_id": "pg7370:main",
                   "corpus_version": "epub-v1-x", "chapter": 5, "section": 27, "text": "every man has a property in his own person"}],
    "self_check": [{"passage_id": "pg7370:main:abc:c0", "quote": "every man has a property in his own person", "status": "ok"}],
    "attempts": 2,
    "info": {"model": "anthropic:claude-sonnet-5-5", "namespace": "ns", "k": 8, "filters": None, "code_sha256": "ab"},
}


def test_real_ask_shape_is_accepted_without_declined_or_claims():
    out = agora.validate_result(REAL_ASK_SHAPE)
    assert out["declined"] is None and out["claims"] is None
    assert out["attempts"] == 2 and out["retrieved"][0]["rank"] == 1
    assert out["info"]["k"] == 8


def test_float_numbers_become_ints_and_missing_rank_is_filled():
    raw = {**REAL_ASK_SHAPE, "attempts": 2.0,
           "retrieved": [{k: v for k, v in REAL_ASK_SHAPE["retrieved"][0].items() if k != "rank"} | {"chapter": 2.0, "section": 27.0},
                         {k: v for k, v in REAL_ASK_SHAPE["retrieved"][0].items() if k != "rank"} | {"passage_id": "p2"}]}
    out = agora.validate_result(raw)
    assert out["retrieved"][0]["chapter"] == 2 and isinstance(out["retrieved"][0]["chapter"], int)
    assert out["attempts"] == 2 and isinstance(out["attempts"], int)
    assert [r["rank"] for r in out["retrieved"]] == [1, 2]


def test_extra_keys_are_kept():
    out = agora.validate_result({**REAL_ASK_SHAPE, "debug": {"x": 1}})
    assert out["debug"] == {"x": 1}


def test_pydantic_object_is_accepted():
    from integrity.common.schema import AgoraResult

    out = agora.validate_result(AgoraResult.model_validate(REAL_ASK_SHAPE))
    assert out["answer"].startswith("Locke")


@pytest.mark.parametrize("bad", [
    {k: v for k, v in REAL_ASK_SHAPE.items() if k != "retrieved"},                      # missing field
    {k: v for k, v in REAL_ASK_SHAPE.items() if k != "answer"},
    {**REAL_ASK_SHAPE, "answer": 5},                                                    # wrong types
    {**REAL_ASK_SHAPE, "citations": "none"},
    {**REAL_ASK_SHAPE, "retrieved": [{"passage_id": "x"}]},
    "just a string", None, [1, 2],
])
def test_contract_violations(bad):
    with pytest.raises(agora.ContractViolation):
        agora.validate_result(bad)


def test_only_agora_adapter_calls_seams_load():
    quiz = ROOT / "integrity" / "quiz"
    for p in quiz.rglob("*.py"):
        text = p.read_text()
        if p.name != "agora.py":
            assert "seams.load" not in text and "import load" not in text, p
    assert time  # keep import used for slow tests elsewhere
