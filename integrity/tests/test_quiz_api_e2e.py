"""B6 end to end: run_quiz, load_scorecard, report, compare, regrade, CLI, independence."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from integrity import cli
from integrity.common import seams, storage
from integrity.common.settings import load_settings
from integrity.quiz import api, report
from integrity.tests import quiz_fake_agora as fa
from integrity.tests import quiz_fixtures as qf

ROOT = Path(__file__).resolve().parents[2]
SPEC = "integrity.tests.quiz_fake_agora:"


@pytest.fixture
def env(data_dir):
    qf.write_sheet(data_dir)
    fa.register()
    return data_dir


def quiz(name="good_agora", **kw):
    kw.setdefault("settings", qf.settings_for())
    kw.setdefault("model_client", qf.RuleJudge())
    return api.run_quiz(agora=SPEC + name, **kw)


def test_run_quiz_end_to_end_writes_every_file(env):
    events = []
    r = quiz(on_progress=events.append)
    assert r.exit_code == 0 and r.run_id.startswith("r-") and r.trust == "TRUSTED"
    for name in ("run.json", "raw.jsonl", "grades.jsonl", "scorecard.json", "scorecard.md", "failures.md"):
        assert (r.run_dir / name).is_file(), name
    kinds = [e["event"] for e in events]
    assert kinds.count("card_started") == 5 and kinds.count("card_finished") == 5 and kinds.count("grading_started") == 1
    assert kinds.index("grading_started") > max(i for i, k in enumerate(kinds) if k == "card_finished")
    raw = storage.read_jsonl(r.run_dir / "raw.jsonl")
    assert len(raw) == 5 and all(x["result"]["info"]["k"] == 8 for x in raw)
    grades = storage.read_jsonl(r.run_dir / "grades.jsonl")
    real = [g for g in grades if not g["is_control"]]
    assert len(real) == 5 and len(grades) == 5 + 14
    for g in grades:
        assert set(g) >= {"card_id", "is_control", "control_kind", "mechanical", "judged", "judge_calls"}
    assert {"coverage", "claims", "support", "refusal", "premise"} <= set(real[0]["judged"])
    assert all(set(c) >= {"prompt_id", "input_sha256", "output", "evidence_ok"} for c in real[0]["judge_calls"])
    idx = storage.read_jsonl(env / "runs" / "index.jsonl")
    assert len(idx) == 1 and idx[0]["run_id"] == r.run_id and idx[0]["sheet_version"] == "v001"
    assert idx[0]["headline"]["found"] == {"n": 3, "d": 3}
    sc = api.load_scorecard("latest", settings=qf.settings_for())
    assert sc["run"]["run_id"] == r.run_id and sc["main"]["found"] == {"n": 3, "d": 3} and sc["holdout"]["cards"] == 1
    assert api.load_scorecard(r.run_id, settings=qf.settings_for())["sheet"]["version"] == "v001"
    assert "Fully passing cards" in (r.run_dir / "scorecard.md").read_text() or "Fully passing" in report.render_terminal(sc)
    assert "did not fully pass" in (r.run_dir / "failures.md").read_text()
    with pytest.raises(FileNotFoundError):
        api.load_scorecard("r-nope", settings=qf.settings_for())


def test_run_quiz_with_fabricating_agora_reports_failures_and_vs_previous(env):
    first = quiz()
    second = quiz("fabricating_agora")
    sc = second.scorecard
    assert sc["main"]["support_counts"]["not_supported"] == 4 and sc["main"]["fully_passing"]["n"] == 0
    assert sc["vs_previous"]["run_id"] == first.run_id and "Faithful" in sc["vs_previous"]["text"]
    assert "planets" in (second.run_dir / "failures.md").read_text()
    out = report.render_terminal(sc)
    assert f"vs {first.run_id} (same sheet)" in out and "Fully passing cards" in out


def test_wrong_passage_is_not_found_but_other_answers_graded(env):
    r = quiz("wrong_passage_agora")
    assert r.scorecard["main"]["found"]["n"] == 0 and "M1 not_found" in (r.run_dir / "failures.md").read_text()


def test_mechanical_only_run(env):
    r = api.run_quiz(agora=SPEC + "good_agora", mechanical_only=True, settings=qf.settings_for())
    assert r.exit_code == 0 and r.scorecard["main"]["judged"] == 0
    text = report.render_terminal(r.scorecard)
    assert "not computed (--mechanical-only)" in text and "not run" in text
    rj = storage.read_json(r.run_dir / "run.json")
    assert rj["grader_version"] is None and rj["judge_model"] is None


def test_strict_untrusted_exits_6_but_saves_files(env):
    r = quiz(model_client=qf.RuleJudge(rubber_stamp=True), strict=True)
    assert r.exit_code == 6 and r.trust == "UNTRUSTED" and (r.run_dir / "scorecard.json").exists()
    assert "UNTRUSTED" in report.render_terminal(r.scorecard)
    assert quiz(model_client=qf.RuleJudge(rubber_stamp=True)).exit_code == 0


def test_strict_same_family_exits_4_after_run_when_discovered_from_info(env, monkeypatch):
    monkeypatch.setitem(fa.INFO, "model", "openai:gpt-4.1")
    r = quiz(strict=True)
    assert r.exit_code == 4 and "same provider family" in r.message


def test_regrade_makes_no_agora_calls_and_links_source(env, monkeypatch):
    s = qf.settings_for()
    first = quiz(settings=s)
    n_calls = len(fa.CALLS)

    def boom(*a, **k):
        raise AssertionError("regrade must not touch Agora")

    monkeypatch.setattr(seams, "load", boom)
    raw_before = (first.run_dir / "raw.jsonl").read_text()
    r = api.regrade(first.run_id, settings=s, model_client=qf.RuleJudge())
    assert r.exit_code == 0 and r.run_id != first.run_id and len(fa.CALLS) == n_calls
    rj = storage.read_json(r.run_dir / "run.json")
    assert rj["source_run"] == first.run_id and rj["sheet_content_sha256"] == storage.read_json(first.run_dir / "run.json")["sheet_content_sha256"]
    assert (r.run_dir / "raw.jsonl").read_text() == raw_before == (first.run_dir / "raw.jsonl").read_text()
    for name in ("grades.jsonl", "scorecard.json", "scorecard.md", "failures.md"):
        assert (r.run_dir / name).exists()
    assert r.scorecard["run"]["source_run"] == first.run_id and "regraded from" in report.render_terminal(r.scorecard)
    assert r.scorecard["main"]["found"] == first.scorecard["main"]["found"]
    assert len(storage.read_jsonl(env / "runs" / "index.jsonl")) == 2


def test_regrade_with_other_judge_model_changes_grader_version_and_compare_gates(env):
    first = quiz(settings=qf.settings_for())
    other = load_settings({"quiz": {"min_cards": 1}, "judge": {"consistency_sample": 0.5, "controls_per_run": 2},
                           "models": {"judge": "openai:gpt-5"}})
    r = api.regrade(first.run_id, settings=other, model_client=qf.RuleJudge())
    assert r.scorecard["run"]["grader_version"] != first.scorecard["run"]["grader_version"]
    cmp = report.compare_scorecards(first.scorecard, r.scorecard)
    assert cmp["ok"] and any("grader versions differ" in n for n in cmp["notes"])
    assert api.regrade("r-nope", settings=other).exit_code == 1


def test_regrade_needs_judge_key(env):
    first = quiz()
    r = api.regrade(first.run_id, settings=qf.settings_for(), env={})
    assert r.exit_code == 4


# --------------------------------------------------------------------------- CLI


@pytest.fixture
def cli_env(env, tmp_path, monkeypatch):
    cfg = tmp_path / "cli.toml"
    cfg.write_text(f'[paths]\ndata_dir = "{env.as_posix()}"\n[quiz]\nmin_cards = 1\nretries = 0\n[judge]\ncontrols_per_run = 1\n')
    monkeypatch.setenv("INTEGRITY_CONFIG", str(cfg))
    return env


def test_cli_quiz_report_compare_roundtrip(cli_env, capsys):
    assert cli.main(["quiz", "--agora", SPEC + "good_agora", "--mechanical-only"]) == 0
    out = capsys.readouterr()
    assert "INTEGRITY QUIZ" in out.out and "HEADLINE" in out.out and "[5/5]" in out.err
    assert cli.main(["report", "latest"]) == 0
    assert capsys.readouterr().out == out.out
    assert cli.main(["report", "--format", "md"]) == 0 and "# Scorecard r-" in capsys.readouterr().out
    assert cli.main(["report", "latest", "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["schema"] == 1
    assert cli.main(["compare", "latest", "latest"]) == 0 and "COMPARE" in capsys.readouterr().out
    assert cli.main(["report", "r-nope"]) == 1
    assert cli.main(["compare", "latest", "r-nope"]) == 1
    assert cli.main(["quiz", "--agora", "nope:nope", "--mechanical-only"]) == 3
    assert cli.main(["quiz", "--cards", "c-x", "--mechanical-only"]) == 1
    assert cli.main(["quiz", "--author", "Mill", "--limit", "1", "--agora", SPEC + "good_agora", "--mechanical-only"]) == 0
    assert cli.main(["quiz", "--namespace", "ns", "--agora", SPEC + "good_agora", "--mechanical-only", "--strict"]) == 0


def test_cli_report_with_no_runs(data_dir, capsys):
    assert cli.main(["report"]) == 1 and "no completed runs" in capsys.readouterr().err


def test_cli_calibrate_without_runs(data_dir, capsys):
    assert cli.main(["calibrate"]) == 1


# --------------------------------------------------------------------------- independence


def test_quiz_api_import_loads_no_builder_modules():
    code = ("import sys, integrity.quiz.api, integrity.quiz.handlers, integrity.quiz.calibrate;"
            "bad=[m for m in sys.modules if m.startswith('integrity.builder')];"
            "assert not bad, bad;"
            "assert 'ask' not in sys.modules and 'ingest' not in sys.modules")
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=False,
                       env={**os.environ, "INTEGRITY_CONFIG": ""})
    assert r.returncode == 0, r.stderr


def test_quiz_sources_never_import_builder():
    for p in (ROOT / "integrity" / "quiz").rglob("*.py"):
        text = p.read_text()
        assert "integrity.builder" not in text and "from integrity import builder" not in text, p
