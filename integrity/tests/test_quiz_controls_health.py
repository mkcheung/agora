"""B5: controls, grader health, calibration."""

import pytest

from integrity.common import storage
from integrity.quiz import api, calibrate, report
from integrity.quiz.agora import validate_result
from integrity.quiz.grading import controls as ctl
from integrity.quiz.grading import health
from integrity.quiz.grading.judge import Judge, ReplayItem
from integrity.quiz.grading.pipeline import grade_one, grade_run
from integrity.tests import quiz_fake_agora as fa
from integrity.tests import quiz_fixtures as qf

SPEC = "integrity.tests.quiz_fake_agora:good_agora"


@pytest.fixture
def sheet(data_dir):
    fa.register()
    return qf.write_sheet(data_dir)


def test_controls_are_identical_for_the_same_sheet(sheet):
    a = ctl.build_controls(sheet, 2)
    b = ctl.build_controls(sheet, 2)
    assert [(c.control_id, c.result) for c in a] == [(c.control_id, c.result) for c in b]
    kinds = [c.kind for c in a]
    assert set(kinds) == set(ctl.KINDS) and len(a) == 14
    assert {c.card.card_id for c in a} <= {c.card_id for c in sheet.cards if not c.holdout and c.type == "passage"}
    assert not ctl.build_controls(sheet, 0)


def test_control_selection_depends_on_sheet_hash(data_dir):
    s1 = qf.write_sheet(data_dir)
    cards = qf.all_cards()
    cards[0]["question"] += " Please explain?"
    s2 = qf.write_sheet(data_dir, version="v002", parent="v001", cards=cards)
    assert s1.content_sha256 != s2.content_sha256


def test_control_construction(sheet):
    by = {c.kind: c for c in ctl.build_controls(sheet, 1)}
    c1, c2, c3, c5, c6, c7 = (by[k] for k in ("C1", "C2", "C3", "C5", "C6", "C7"))
    kps = c1.card.key_points
    assert kps and all(k.statement.rstrip(".") in c1.result["answer"] for k in kps)
    assert f"({c1.card.anchor.author}, {c1.card.anchor.work}, {c1.card.anchor.locator})" in c1.result["answer"]
    assert [c["quote"] for c in c1.result["citations"]] == [k.quote for k in kps]
    assert len(c2.result["citations"]) == len(kps) - 1 and c2.info["omitted"] == kps[-1].id
    assert "movements of the planets" in c3.result["answer"] or c3.info["fabricated"] in c3.result["answer"]
    assert len(c5.result["citations"][0]["quote"].split()) == 2
    assert c6.result["citations"][0]["passage_id"] == "bogus:id:c0"
    assert c7.result["citations"] == [] and "do not answer" in c7.result["answer"]
    assert by["C4"].must_pass is False
    assert {k: v.must_pass for k, v in by.items()} == ctl.MUST_PASS


def run_graded(sheet, judge, settings=None):
    settings = settings or qf.settings_for()
    records = [{"card_id": c.card_id, "result": validate_result(fa._good(c.model_dump())), "error": None} for c in sheet.cards]
    return grade_run(sheet=sheet, cards=sheet.cards, records=records, judge=judge, settings=settings)


def judge_for(client, settings=None):
    return Judge.from_settings(client, settings or qf.settings_for())


def test_good_grader_is_trusted_and_controls_pass(sheet):
    g = run_graded(sheet, judge_for(qf.RuleJudge()))
    h = g.health
    assert h["label"] == "TRUSTED" and h["trusted"] is True
    assert h["controls"]["must_pass_total"] == 12 and h["controls"]["must_pass_passed"] == 12
    assert h["controls"]["informational_total"] == 2
    controls = [x for x in g.grades if x["is_control"]]
    assert len(controls) == 14 and all(x["control_kind"] in ctl.KINDS for x in controls)
    assert h["evidence"]["rejected"] == 0 and h["evidence"]["checked"] > 0
    assert h["claim_coverage"] and h["claim_coverage"] > 0.9 and not h["claim_coverage_low"]


def test_judge_that_misses_c3_makes_judged_metrics_untrusted(sheet):
    g = run_graded(sheet, judge_for(qf.RuleJudge(rubber_stamp=True)))
    assert g.health["label"] == "UNTRUSTED" and g.health["trusted"] is False
    failed = {c["kind"] for c in g.health["controls"]["failed"]}
    assert "C3" in failed
    assert any("C3 failed" in r for r in g.health["reasons"])


def test_controls_are_excluded_from_agora_scores(sheet):
    from integrity.quiz import scorecard
    g = run_graded(sheet, judge_for(qf.RuleJudge()))
    sc = scorecard.build_scorecard(run={"run_id": "r-x"}, sheet=sheet, cards=sheet.cards, grades=g.grades,
                                   raw=[{"card_id": c.card_id, "result": None} for c in sheet.cards], health=g.health,
                                   never_retrieved=[], warnings=[])
    assert len(sc["cards"]) == 5 and sc["cards"] and not any(c["card_id"].startswith("ctl") for c in sc["cards"])


def test_mechanical_only_controls_check_mechanical_parts(sheet):
    g = run_graded(sheet, None)
    h = g.health
    assert h["label"].startswith("NOT RUN") and h["trusted"] is None
    evals = {(e["kind"]): e["passed"] for e in h["controls"]["evals"]}
    assert evals["C5"] is True and evals["C6"] is True and evals["C1"] is True and evals["C3"] is None


def test_control_expected_outcome_failures_are_detected(sheet):
    c5 = next(c for c in ctl.build_controls(sheet, 1) if c.kind == "C5")
    g, _ = grade_one(c5.card, c5.result, None, None, 5)
    assert ctl.evaluate(c5, g, judged=False)["passed"] is True
    g["mechanical"]["trivial_quotes"] = 0
    assert ctl.evaluate(c5, g, judged=False)["passed"] is False
    c6 = next(c for c in ctl.build_controls(sheet, 1) if c.kind == "C6")
    g, _ = grade_one(c6.card, c6.result, None, None, 5)
    assert len(g["mechanical"]["invalid_ids"]) == 1


def test_consistency_sample_is_reproducible_and_order_independent():
    def item(i, flip=False):
        return ReplayItem(f"c{i}", "support", "cl1", "supported", lambda: ("not_supported" if flip else "supported", {"calls": []}))

    items = [item(i, flip=i % 4 == 0) for i in range(20)]
    a = health.select_sample(items, 0.25, seed=7)
    b = health.select_sample(list(reversed(items)), 0.25, seed=7)
    assert [i.card_id for i in a] == [i.card_id for i in b] and len(a) == 5
    assert [i.card_id for i in a] != [i.card_id for i in health.select_sample(items, 0.25, seed=8)]
    res = health.run_consistency(items, 0.25, 7)
    assert res["sampled"] == 5 and res["agreed"] == sum(1 for i in a if int(i.card_id[1:]) % 4 != 0)
    assert res["pct"] == round(100 * res["agreed"] / 5, 1)
    assert health.run_consistency(items, 0, 7)["sampled"] == 0
    assert health.consistency_seed("ab" * 32) == health.consistency_seed("ab" * 32)


def test_consistency_in_pipeline_is_reproducible(sheet):
    g1 = run_graded(sheet, judge_for(qf.RuleJudge()))
    g2 = run_graded(sheet, judge_for(qf.RuleJudge()))
    assert [(r["card_id"], r["key"]) for r in g1.consistency["rows"]] == [(r["card_id"], r["key"]) for r in g2.consistency["rows"]]
    assert g1.consistency["sampled"] > 0 and g1.consistency["agreed"] == g1.consistency["sampled"]
    assert any(c.get("consistency") for g in g1.grades for c in g["judge_calls"])


def test_calibrate_appends_records_keyed_by_grader_version_and_scorecard_shows_it(sheet, data_dir):
    s = qf.settings_for()
    r = api.run_quiz(agora=SPEC, settings=s, model_client=qf.RuleJudge())
    assert "not yet calibrated" in report.render_terminal(r.scorecard)
    answers = iter(["a", "a", "d", "u", "x", "a"])
    out = []
    code = calibrate.calibrate(s, r.run_id, 4, ask=lambda _: next(answers), out=out.append)
    assert code == 0
    recs = storage.read_jsonl(health.calibration_path(data_dir))
    gv = storage.read_json(r.run_dir / "run.json")["grader_version"]
    assert len(recs) == 4 and {x["grader_version"] for x in recs} == {gv} and [x["owner"] for x in recs] == ["agree", "agree", "disagree", "unsure"]
    assert health.calibration_summary(data_dir, gv) == {"n": 4, "agree": 2, "disagree": 1, "unsure": 1}
    assert health.calibration_summary(data_dir, "g-other") is None
    again = api.run_quiz(agora=SPEC, settings=s, model_client=qf.RuleJudge())
    assert f"owner agreement 2/4 (grader {gv})" in report.render_terminal(again.scorecard)
    # holdout cards are never shown to the owner
    shown = "\n".join(out)
    assert "partnership" not in shown


def test_calibrate_quit_and_mechanical_run(sheet):
    s = qf.settings_for()
    r = api.run_quiz(agora=SPEC, settings=s, mechanical_only=True)
    with pytest.raises(ValueError):
        calibrate.sample_items(s, r.run_id, 3)
