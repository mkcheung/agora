"""B6: scoring formulas, golden-file rendering, holdout hiding, compare rules."""

import copy
import os
from pathlib import Path

import pytest

from integrity.quiz import report, scorecard
from integrity.quiz.agora import validate_result
from integrity.quiz.grading.judge import Judge
from integrity.quiz.grading.pipeline import grade_run
from integrity.tests import quiz_fake_agora as fa
from integrity.tests import quiz_fixtures as qf

GOLDEN = Path(__file__).parent / "quiz_golden"
FIXED_RUN = {
    "run_id": "r-20261121-093000", "started_at": "2026-11-21T09:30:00Z", "finished_at": "2026-11-21T09:41:00Z",
    "sheet_version": "v001", "grader_version": None, "judge_model": "openai:gpt-4.1", "mechanical_only": False,
    "entrypoint": "ask:answer_question", "namespace": "epub-v1-04b8672ea20df6c7", "agora_model": "anthropic:claude-sonnet-5-5",
    "k": 8, "git_commit": "1a2b3c4d5e6f7a8b9c0d1a2b3c4d5e6f7a8b9c0d", "git_dirty": True, "textnorm_version": 1,
    "module_version": "0.1.0", "source_run": None, "files_dir": "integrity_data/runs/r-20261121-093000",
}


def summ(**o):
    base = {"card_id": "c-1", "author": "A", "work": "W", "type": "passage", "holdout": False, "expected_behavior": "answer",
            "error": None, "judged": True, "block_hit": True, "block_rank": 1, "near_hit": None, "evidence_found": 2,
            "evidence_total": 2, "cited_block": True, "quotes_verified": 2, "quotes_total": 2, "trivial": 0, "invalid_ids": 0,
            "label_mismatches": 0, "no_citations": False, "self_check_disagreements": 0, "declined": False,
            "coverage": {"covered": 2, "partial": 0, "absent": 0, "unverified": 0, "judge_error": 0}, "points_total": 2,
            "points_score": 2.0, "claims": {"total": 2, "supported": 2, "not_supported": 0, "contradicted": 0, "unverified": 0,
                                            "judge_error": 0, "uncited": 0},
            "claims_unsupported_any": False, "wrongful_refusal": False, "refusal_ok": True, "premise_corrected": None,
            "fully_passing": True, "failed_checks": [], "failures": []}
    return base | o


def test_scoring_formulas():
    cards = [
        summ(card_id="a", block_rank=1),
        summ(card_id="b", block_hit=True, block_rank=4, points_score=1.5, coverage={"covered": 1, "partial": 1, "absent": 0, "unverified": 0, "judge_error": 0},
             claims={"total": 3, "supported": 1, "not_supported": 1, "contradicted": 1, "unverified": 0, "judge_error": 0, "uncited": 1},
             claims_unsupported_any=True, fully_passing=False, trivial=1),
        summ(card_id="c", block_hit=False, block_rank=None, near_hit=True, evidence_found=0, cited_block=False, quotes_verified=1,
             points_score=0.0, wrongful_refusal=True, refusal_ok=False, fully_passing=False, no_citations=True,
             coverage={"covered": 0, "partial": 0, "absent": 2, "unverified": 0, "judge_error": 0},
             claims={"total": 0, "supported": 0, "not_supported": 0, "contradicted": 0, "unverified": 0, "judge_error": 0, "uncited": 0}),
        summ(card_id="d", type="false_premise", expected_behavior="correct_premise", premise_corrected=True, block_rank=2),
        summ(card_id="e", error="timeout", judged=False, failed_checks=["error"]),
    ]
    m = scorecard.compute_metrics(cards)
    assert (m["cards"], m["scored"], m["errors"], m["answerable"]) == (5, 4, 1, 3)
    assert m["found"] == {"n": 2, "d": 3}                           # answerable only; the premise card is not counted
    assert m["rank_distribution"] == {"1": 1, "4": 1}
    assert m["mrr"] == pytest.approx((1 + 0.25 + 0) / 3) and m["near_hits"] == 1
    assert m["evidence_recall"]["mean"] == pytest.approx((1 + 1 + 0 + 1) / 4)
    assert m["complete"] == {"n": 2 + 1.5 + 0 + 2, "d": 8}         # covered 1, partial .5, absent 0
    assert m["faithful"] == {"n": 2 + 1 + 0 + 2, "d": 2 + 3 + 0 + 2}
    assert m["support_counts"]["contradicted"] == 1 and m["support_counts"]["uncited"] == 1
    assert m["answers_with_unsupported"] == 1
    c = m["citations"]
    assert c["cited_block"] == {"n": 2, "d": 3} and c["quotes_verified"] == {"n": 7, "d": 8} and c["trivial"] == 1 and c["no_citations"] == 1
    assert m["behaviour"]["wrongful_refusals"] == 1 and m["behaviour"]["premise_corrected"] == {"n": 1, "d": 1}
    assert m["fully_passing"] == {"n": 2, "d": 4}


def test_unverified_and_judge_error_do_not_favour_agora():
    s = summ(coverage={"covered": 1, "partial": 0, "absent": 0, "unverified": 1, "judge_error": 0}, points_score=1.0,
             claims={"total": 3, "supported": 1, "not_supported": 0, "contradicted": 0, "unverified": 1, "judge_error": 1, "uncited": 0})
    m = scorecard.compute_metrics([s])
    assert m["complete"] == {"n": 1.0, "d": 2} and m["faithful"] == {"n": 1, "d": 3}
    assert m["support_counts"]["unverified"] == 1 and m["support_counts"]["judge_error"] == 1


def test_mechanical_only_summaries_have_no_judged_metrics():
    s = summ(judged=False)
    for k in ("coverage", "points_total", "points_score", "claims", "wrongful_refusal", "fully_passing"):
        s.pop(k)
    s.update(claims_unsupported_any=None, premise_corrected=None, fully_passing=None)
    m = scorecard.compute_metrics([s])
    assert m["judged"] == 0 and m["complete"] == {"n": 0, "d": 0} and m["found"] == {"n": 1, "d": 1}


# --------------------------------------------------------------------------- golden files


def build_golden_scorecard():
    cards = {c["anchor"]["author"] + c["type"]: c for c in qf.all_cards()}
    sheet = qf.write_sheet_obj()
    fa.register()
    plan = {"John Lockepassage": fa.fabricating_agora, "Thomas Hobbespassage": fa.good_agora,
            "J. S. Millpassage": fa.wrong_passage_agora, "Edmund Burkepassage": fa.fabricating_agora,
            "John Lockefalse_premise": None}
    records = []
    for sc_card in sorted(sheet.cards, key=lambda c: c.card_id):
        key = sc_card.anchor.author + sc_card.type
        fn = plan[key]
        if fn is None:
            records.append({"card_id": sc_card.card_id, "question": sc_card.question, "result": None,
                            "error": {"type": "timeout", "message": "no answer within 180s"}})
        else:
            records.append({"card_id": sc_card.card_id, "question": sc_card.question, "result": validate_result(fn(sc_card.question)),
                            "error": None})
    assert cards
    settings = qf.settings_for()
    judge = Judge.from_settings(qf.RuleJudge(), settings)
    graded = grade_run(sheet=sheet, cards=sheet.cards, records=records, judge=judge, settings=settings)
    run = dict(FIXED_RUN, grader_version=judge.grader_version)
    return scorecard.build_scorecard(run=run, sheet=sheet, cards=sheet.cards, grades=graded.grades, raw=records,
                                     health=graded.health, never_retrieved=graded.never_retrieved, warnings=[])


def check_golden(name, text):
    path = GOLDEN / name
    if os.environ.get("UPDATE_GOLDEN") == "1":
        path.write_text(text, encoding="utf-8")
    assert path.read_text(encoding="utf-8") == text, f"{name} differs from the golden file (UPDATE_GOLDEN=1 regenerates)"


@pytest.fixture
def golden_sc(data_dir, monkeypatch):
    sc = build_golden_scorecard()
    sc["run"]["grader_version"] = "g-golden"
    sc["health"]["grader_version"] = "g-golden"
    return sc


def test_golden_terminal(golden_sc):
    check_golden("terminal.txt", report.render_terminal(golden_sc))


def test_golden_scorecard_md(golden_sc):
    check_golden("scorecard.md", report.render_scorecard_md(golden_sc))


def test_golden_failures_md(golden_sc):
    check_golden("failures.md", report.render_failures_md(golden_sc))


def test_holdout_details_are_hidden_everywhere(golden_sc):
    import json
    burke_q, burke_stmt = "partnership", "The state is more than a partnership in trade"
    blob = json.dumps(golden_sc)
    for out in (blob, report.render_terminal(golden_sc), report.render_scorecard_md(golden_sc), report.render_failures_md(golden_sc)):
        assert burke_q not in out.replace("partnership agreement in a trade", "") or "Does Burke" not in out
        assert burke_stmt not in out and "Does Burke think" not in out
        assert "pepper and coffee" not in out
    hold = [c for c in golden_sc["cards"] if c["holdout"]]
    assert len(hold) == 1 and "detail" not in hold[0] and hold[0]["failures"] == [] and hold[0]["failed_checks"]
    assert "Sealed holdout cards (details hidden)" in report.render_failures_md(golden_sc)
    assert golden_sc["holdout"]["cards"] == 1 and golden_sc["main"]["cards"] == 4


def test_untrusted_label_in_every_output(golden_sc):
    sc = copy.deepcopy(golden_sc)
    sc["trust"] = {"label": "UNTRUSTED", "trusted": False, "reasons": ["C3 failed on c-1: x"]}
    sc["health"].update(label="UNTRUSTED", trusted=False)
    assert "UNTRUSTED" in report.render_terminal(sc) and "UNTRUSTED" in report.render_scorecard_md(sc)
    assert report.render_terminal(sc).count("[UNTRUSTED]") >= 4


# --------------------------------------------------------------------------- compare


def tweak(sc, run_id, **main_over):
    out = copy.deepcopy(sc)
    out["run"]["run_id"] = run_id
    for k, v in main_over.items():
        out["main"][k] = v
    return out


def test_compare_noise_rules(golden_sc):
    a = golden_sc
    b = tweak(a, "r-b", found={"n": a["main"]["found"]["n"] + 1, "d": a["main"]["found"]["d"]},
              complete={"n": a["main"]["complete"]["n"] + 1, "d": a["main"]["complete"]["d"]},
              faithful={"n": a["main"]["faithful"]["n"] - 3, "d": a["main"]["faithful"]["d"]})
    cmp = report.compare_scorecards(a, b)
    rows = {r["key"]: r for r in cmp["rows"]}
    assert cmp["ok"] and rows["found"]["delta"] == 1 and rows["found"]["noise"] is True       # at most 1 card
    assert rows["complete"]["noise"] is True                                                  # at most 1 key point
    assert rows["faithful"]["delta"] == -3 and rows["faithful"]["noise"] is False            # beyond (1-consistency) x N
    c = tweak(a, "r-c", found={"n": a["main"]["found"]["n"] + 2, "d": a["main"]["found"]["d"]})
    assert {r["key"]: r for r in report.compare_scorecards(a, c)["rows"]}["found"]["noise"] is False
    text = report.render_compare(cmp)
    assert "(within noise)" in text and "COMPARE" in text and report.brief(cmp).startswith("Found +1 (within noise)")


def test_compare_refuses_different_sheets_unless_forced(golden_sc):
    b = tweak(golden_sc, "r-b")
    b["run"]["sheet_version"] = "v002"
    cmp = report.compare_scorecards(golden_sc, b)
    assert not cmp["ok"] and "different sheets" in cmp["error"] and "different sheets" in report.render_compare(cmp)
    forced = report.compare_scorecards(golden_sc, b, force=True)
    assert forced["ok"] and any("shared cards" in n for n in forced["notes"])


def test_compare_grader_versions_gate_judged_metrics(golden_sc):
    b = tweak(golden_sc, "r-b")
    b["run"]["grader_version"] = "g-other"
    cmp = report.compare_scorecards(golden_sc, b)
    keys = {r["key"] for r in cmp["rows"]}
    assert cmp["ok"] and "found" in keys and "complete" not in keys and "faithful" not in keys
    assert any("grader versions differ" in n for n in cmp["notes"])
    forced = report.compare_scorecards(golden_sc, b, force=True)
    assert "complete" in {r["key"] for r in forced["rows"]}


def test_compare_refuses_other_textnorm_version(golden_sc):
    b = tweak(golden_sc, "r-b")
    b["run"]["textnorm_version"] = 2
    cmp = report.compare_scorecards(golden_sc, b, force=True)
    assert not cmp["ok"] and "textnorm" in cmp["error"]
