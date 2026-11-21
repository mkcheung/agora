"""Findings from the first live quiz run (2026-11-21), both in the module's own grading rules.

1. Controls C2/C3 were too literal: the live judge said "partial" for an omitted key point whose neighbour overlapped
   it (C2) and "contradicted" for the planted false claim (C3). Both mean the judge did not accept the mistake.
2. Honest Agora answers leave a lead-in sentence uncited (the judge found every such claim supported), so "any
   uncited claim blocks a pass" made 'fully passing' nearly impossible.
"""

import copy

import pytest

from integrity.common.schema import Card
from integrity.quiz import scorecard
from integrity.quiz.agora import validate_result
from integrity.quiz.grading import controls as ctl
from integrity.quiz.grading.judge import Judge
from integrity.quiz.grading.pipeline import grade_one, grade_run
from integrity.tests import quiz_fake_agora as fa
from integrity.tests import quiz_fixtures as qf


@pytest.fixture
def sheet(data_dir):
    fa.register()
    return qf.write_sheet(data_dir)


def graded_controls(sheet):
    settings = qf.settings_for()
    records = [{"card_id": c.card_id, "result": validate_result(fa._good(c.model_dump())), "error": None} for c in sheet.cards]
    g = grade_run(sheet=sheet, cards=sheet.cards, records=records, judge=Judge.from_settings(qf.RuleJudge(), settings),
                  settings=settings)
    by_key = {(x["card_id"], x["control_kind"]): x for x in g.grades if x["is_control"]}
    controls = ctl.build_controls(sheet, settings.judge.controls_per_run)
    return controls, by_key


# --------------------------------------------------------------------------- controls


def test_c2_accepts_partial_for_the_omitted_point_but_never_covered(sheet):
    controls, grades = graded_controls(sheet)
    checked = 0
    for control in (c for c in controls if c.kind == "C2"):
        grade = copy.deepcopy(grades[(control.card.card_id, "C2")])
        omitted = control.info["omitted"]
        verdicts = {}
        for verdict in ("absent", "partial", "covered", "unverified"):
            for item in grade["judged"]["coverage"]:
                if item["kp_id"] == omitted:
                    item["verdict"] = verdict
            verdicts[verdict] = ctl.evaluate(control, grade)["passed"]
        assert verdicts == {"absent": True, "partial": True, "covered": False, "unverified": False}
        checked += 1
    assert checked >= 1


def test_c3_accepts_contradicted_for_the_planted_claim_but_never_supported(sheet):
    controls, grades = graded_controls(sheet)
    checked = 0
    for control in (c for c in controls if c.kind == "C3"):
        grade = copy.deepcopy(grades[(control.card.card_id, "C3")])
        verdicts = {}
        for verdict in ("not_supported", "contradicted", "supported"):
            for item in grade["judged"]["support"]:
                item["verdict"] = verdict
            verdicts[verdict] = ctl.evaluate(control, grade)["passed"]
        assert verdicts == {"not_supported": True, "contradicted": True, "supported": False}
        checked += 1
    assert checked >= 1


# --------------------------------------------------------------------------- uncited claims


def card_and_grade(sheet):
    card = next(c for c in sheet.cards if c.type == "passage" and not c.holdout)
    result = validate_result(fa._good(card.model_dump()))
    grade, _ = grade_one(card, result, None, Judge.from_settings(qf.RuleJudge(), qf.settings_for()), 5)
    return card, grade


def with_uncited(grade, n_uncited):
    """Make ``n_uncited`` of the claims uncited, keeping every verdict 'supported' (an honest, true lead-in)."""
    g = copy.deepcopy(grade)
    items = [c for c in g["judged"]["claims"]["items"] if c["kind"] == "substantive"]
    for claim in items[:n_uncited]:
        claim["cited_ids"] = []
        claim["citation_unmapped"] = False
        claim["unmapped"] = False
    return g, len(items)


def test_an_uncited_lead_in_claim_does_not_block_a_pass(sheet):
    card, grade = card_and_grade(sheet)
    base = scorecard.summarize_card(card, grade, None)
    assert base["fully_passing"] is True and base["claims"]["uncited"] == 0   # the control case passes to begin with
    g, n = with_uncited(grade, 1)
    assert n >= 2
    s = scorecard.summarize_card(card, g, None)
    assert s["claims"]["uncited"] == 1                       # still reported ...
    assert s["fully_passing"] is True                        # ... but it does not block the pass
    assert not any(f["check"] == "J3 uncited_claims" for f in s["failures"])


def test_a_mostly_uncited_answer_still_cannot_fully_pass(sheet):
    card, grade = card_and_grade(sheet)
    _, n = with_uncited(grade, 0)
    g, _ = with_uncited(grade, n)                            # every claim uncited, all supported
    s = scorecard.summarize_card(card, g, None)
    assert s["claims"]["uncited"] == n and s["fully_passing"] is False
    assert any(f["check"] == "J3 uncited_claims" for f in s["failures"])


def test_an_uncited_claim_that_is_unsupported_still_fails_through_faithful(sheet):
    card, grade = card_and_grade(sheet)
    g, _ = with_uncited(grade, 1)
    uncited = next(c for c in g["judged"]["claims"]["items"] if not c.get("cited_ids") and c["kind"] == "substantive")
    for item in g["judged"]["support"]:
        if item["claim_id"] == uncited["claim_id"]:
            item["verdict"] = "not_supported"
    s = scorecard.summarize_card(card, g, None)
    assert s["claims_unsupported_any"] is True and s["fully_passing"] is False


def test_no_citations_at_all_still_blocks_a_pass(sheet):
    card, grade = card_and_grade(sheet)
    g = copy.deepcopy(grade)
    g["mechanical"]["no_citations"] = True
    s = scorecard.summarize_card(card, g, None)
    assert s["fully_passing"] is False
    assert any(f["check"] == "M9 no_citations" for f in s["failures"])


def test_fixture_card_is_a_card(sheet):
    assert all(isinstance(c, Card) for c in sheet.cards)
