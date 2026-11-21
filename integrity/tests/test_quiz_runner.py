"""B2: runner, run.json, raw.jsonl, lock, exit codes."""

import pytest

from integrity.common import storage
from integrity.common.schema import Card
from integrity.quiz import api, runner
from integrity.quiz import preflight as pf
from integrity.quiz.agora import AgoraAdapter
from integrity.tests import quiz_fake_agora as fa
from integrity.tests import quiz_fixtures as qf

SPEC = "integrity.tests.quiz_fake_agora:"


@pytest.fixture
def env(data_dir):
    sheet = qf.write_sheet(data_dir)
    fa.register()
    yield sheet
    fa.RELEASE.set()


def adapter(name):
    from integrity.common.settings import load_settings
    a = AgoraAdapter(SPEC + name, load_settings().project_root)
    a.load()
    return a


def cards(sheet):
    return sorted(sheet.cards, key=lambda c: c.card_id)


def test_lines_appended_as_each_card_finishes(env, tmp_path):
    seen = []

    def on(e):
        if e["event"] == "card_finished":
            seen.append(len(storage.read_jsonl(tmp_path / "raw.jsonl")))
        if e["event"] == "card_started":
            assert e["total"] == 5

    out = runner.run_cards(cards(env), adapter("good_agora"), tmp_path, timeout_s=5, retries=0, on_progress=on)
    assert seen == [1, 2, 3, 4, 5]
    assert [r["card_id"] for r in out.records] == [c.card_id for c in cards(env)]
    line = storage.read_jsonl(tmp_path / "raw.jsonl")[0]
    assert set(line) >= {"card_id", "question", "started_at", "latency_s", "result", "error"}
    assert fa.CALLS == [c.question for c in cards(env)]  # only the question is passed, one at a time


def test_exceptions_become_error_lines_and_run_continues(env, tmp_path):
    out = runner.run_cards(cards(env), adapter("raising_agora"), tmp_path, timeout_s=5, retries=0)
    assert len(out.records) == 5 and out.all_errored
    assert out.records[0]["error"] == {"type": "RuntimeError", "message": "agora exploded"}


def test_timeout_is_an_error_line_and_is_noted(env, tmp_path):
    out = runner.run_cards(cards(env)[:2], adapter("slow_agora"), tmp_path, timeout_s=0.1, retries=0)
    assert [r["error"]["type"] for r in out.records] == ["timeout", "timeout"]
    assert len(out.timeouts) == 2


def test_retry_then_success(env, tmp_path):
    out = runner.run_cards(cards(env)[:1], adapter("flaky_once_agora"), tmp_path, timeout_s=5, retries=1)
    assert out.records[0]["error"] is None and out.records[0]["attempts"] == 2


def test_contract_violation_is_never_retried(env, tmp_path):
    fa.register()
    out = runner.run_cards(cards(env)[:1], adapter("contract_violating_agora"), tmp_path, timeout_s=5, retries=3)
    assert fa.CALLS.count(cards(env)[0].question) == 1
    assert out.records[0]["error"]["type"] == "contract_violation"


def test_first_card_violation_aborts_with_exit_3(env, tmp_path):
    out = runner.run_cards(cards(env), adapter("contract_violating_agora"), tmp_path, timeout_s=5, retries=0)
    assert out.aborted and out.aborted[0] == 3 and "Agora entrypoint contract" in out.aborted[1]
    assert len(out.records) == 1


def test_later_violation_is_a_per_card_error(env, tmp_path):
    out = runner.run_cards(cards(env), adapter("violating_after_first_agora"), tmp_path, timeout_s=5, retries=0)
    assert out.aborted is None and len(out.records) == 5
    assert out.records[0]["error"] is None
    assert out.records[1:] and all(r["error"]["type"] == "contract_violation" for r in out.records[1:])
    assert not out.all_errored


def test_resume_skips_finished_cards(env, tmp_path):
    cs = cards(env)
    runner.run_cards(cs[:2], adapter("good_agora"), tmp_path, timeout_s=5, retries=0)
    fa.CALLS.clear()
    out = runner.run_cards(cs, adapter("good_agora"), tmp_path, timeout_s=5, retries=0)
    assert fa.CALLS == [c.question for c in cs[2:]]
    assert len(out.records) == 5 and len(storage.read_jsonl(tmp_path / "raw.jsonl")) == 5
    assert out.first_info["model"] == "anthropic:claude-sonnet-5-5"


# --------------------------------------------------------------------------- through the API


def test_all_cards_errored_exits_5(env):
    r = api.run_quiz(agora=SPEC + "raising_agora", settings=qf.settings_for(), mechanical_only=True)
    assert r.exit_code == 5 and r.scorecard is None
    assert (r.run_dir / "raw.jsonl").exists()


def test_first_card_contract_violation_exits_3(env):
    r = api.run_quiz(agora=SPEC + "contract_violating_agora", settings=qf.settings_for(), mechanical_only=True)
    assert r.exit_code == 3 and "contract" in r.message
    assert storage.read_json(r.run_dir / "run.json")["status"] == "aborted"


def test_lock_blocks_concurrent_run_and_is_released(env):
    lock = storage.FileLock(storage.runs_lock_path(qf.settings_for().data_dir))
    lock.acquire()
    try:
        r = api.run_quiz(agora=SPEC + "good_agora", settings=qf.settings_for(), mechanical_only=True)
        assert r.exit_code == 4
    finally:
        lock.release()
    r = api.run_quiz(agora=SPEC + "good_agora", settings=qf.settings_for(), mechanical_only=True)
    assert r.exit_code == 0
    assert not storage.runs_lock_path(qf.settings_for().data_dir).exists()


def test_run_json_has_every_5_4_field(env):
    r = api.run_quiz(agora=SPEC + "good_agora", namespace="ns-x", settings=qf.settings_for(), model_client=qf.RuleJudge())
    rj = storage.read_json(r.run_dir / "run.json")
    for key in ("run_id", "started_at", "finished_at", "sheet_version", "sheet_content_sha256", "grader_version",
                "judge_model", "prompt_hashes", "entrypoint", "namespace", "agora_info", "git_commit", "git_dirty",
                "module_version", "options", "preflight"):
        assert key in rj, key
    assert rj["sheet_version"] == "v001" and rj["namespace"] == "ns-x" and rj["agora_info"]["k"] == 8
    assert rj["entrypoint"] == SPEC + "good_agora" and len(rj["prompt_hashes"]) == 5
    assert rj["grader_version"].startswith("g-") and rj["finished_at"]
    assert set(rj["preflight"]["checks"]) >= {"P1", "P2", "P3", "P4", "P5", "P6", "P7"}
    assert rj["git_commit"] is None or len(rj["git_commit"]) == 40


def test_resume_via_api_skips_finished_cards(env):
    s = qf.settings_for()
    first = api.run_quiz(agora=SPEC + "good_agora", limit=2, settings=s, model_client=qf.RuleJudge())
    done = {c for c in fa.CALLS}
    fa.CALLS.clear()
    again = api.run_quiz(agora=SPEC + "good_agora", resume=first.run_id, settings=s, model_client=qf.RuleJudge())
    assert again.run_id == first.run_id and again.exit_code == 0
    assert not (set(fa.CALLS) & done) and len(fa.CALLS) == 3
    assert len(storage.read_jsonl(first.run_dir / "raw.jsonl")) == 5
    assert "resumed_at" in storage.read_json(first.run_dir / "run.json")
    assert api.run_quiz(resume="r-nope", settings=s).exit_code == 1


def test_resume_refuses_other_sheet(env):
    s = qf.settings_for()
    first = api.run_quiz(agora=SPEC + "good_agora", limit=1, settings=s, mechanical_only=True)
    qf.write_sheet(qf.settings_for().data_dir, version="v002", parent="v001", cards=qf.all_cards()[:3])
    assert api.run_quiz(sheet="v002", resume=first.run_id, settings=s).exit_code == 1


def test_card_model_roundtrip(env):
    assert isinstance(cards(env)[0], Card) and pf.scorable(cards(env)[0])
