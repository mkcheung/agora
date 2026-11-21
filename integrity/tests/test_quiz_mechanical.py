"""B3: mechanical grading M1-M12, table-driven."""

import copy

import pytest

from integrity.common.schema import Card
from integrity.quiz.agora import validate_result
from integrity.quiz.grading import mechanical as mech
from integrity.tests import quiz_fake_agora as fa
from integrity.tests import quiz_fixtures as qf

RAW = {c["key_points"][0]["id"] + c["card_id"]: c for c in qf.all_cards()}
BY_AUTHOR = {c["anchor"]["author"] + c["type"]: c for c in qf.all_cards()}
LOCKE = BY_AUTHOR["John Lockepassage"]
MILL = BY_AUTHOR["J. S. Millpassage"]
BURKE = BY_AUTHOR["Edmund Burkepassage"]
HOBBES = BY_AUTHOR["Thomas Hobbespassage"]


def grade(card_dict, result=None, **kw):
    result = validate_result(result if result is not None else fa._good(card_dict))
    return mech.grade_mechanical(Card.model_validate(card_dict), result, **kw)


def test_good_answer_all_clean():
    g = grade(LOCKE)
    assert g["block_hit"] and g["block_rank"] == 1 and g["block_hit_method"] == "id"
    assert g["evidence_recall"] == 1.0 and g["cited_block"] and g["near_hit"] is None
    assert g["quotes_verified"]["verified"] == g["quotes_verified"]["total"] == 3
    assert g["trivial_quotes"] == 0 and g["invalid_ids"] == [] and g["label_mismatches"] == []
    assert g["no_citations"] is False and g["self_check_disagreements"] == [] and g["declined"] is None
    assert g["ids_trusted"] and not g["corpus_version_mismatch"] and g["error"] is None


def test_error_record_m12():
    g = mech.grade_mechanical(Card.model_validate(LOCKE), None, {"type": "timeout", "message": "slow"})
    assert g == {"error": {"type": "timeout", "message": "slow"}}


def test_float_metadata_converted_to_int():
    out = validate_result(fa._good(LOCKE))
    assert out["retrieved"][0]["chapter"] == 5 and isinstance(out["retrieved"][0]["section"], int)


def test_id_trust_depends_on_corpus_version():
    # retrieved text no longer contains the quotes, but the block id matches
    r = fa._good(LOCKE)
    r["retrieved"][0]["text"] = "something else entirely"
    assert grade(LOCKE, r)["block_hit"] is True and grade(LOCKE, r)["block_hit_method"] == "id"
    other = copy.deepcopy(r)
    other["retrieved"][0]["corpus_version"] = "epub-v2-other"
    g = grade(LOCKE, other)
    assert g["block_hit"] is False and g["ids_trusted"] is False and g["corpus_version_mismatch"] is True


def test_generation_mismatch_falls_back_to_text_containment():
    r = fa._good(LOCKE)
    for it in r["retrieved"]:
        it["corpus_version"] = "epub-v2-other"
        it["block_id"] = "changed:id"
    g = grade(LOCKE, r)
    assert g["block_hit"] and g["block_hit_method"] == "text" and g["cited_block"]  # M4 via quote in anchor text


def test_text_containment_fallback_without_id_fields():
    r = fa._good(LOCKE)
    for it in r["retrieved"]:
        for k in ("block_id", "work_id", "corpus_version"):
            del it[k]
    g = grade(LOCKE, r)
    assert g["block_hit"] and g["block_hit_method"] == "text" and g["ids_trusted"] is False


def test_block_hit_on_split_paragraph_by_any_chunk_and_rank():
    r = fa._good(MILL)
    r["retrieved"] = [dict(r["retrieved"][1], rank=3)]  # only the second chunk (c1)
    r["retrieved"].insert(0, dict(fa._good(LOCKE)["retrieved"][0], rank=1))
    g = grade(MILL, r)
    assert g["block_hit"] and g["block_rank"] == 3
    assert g["evidence_recall"] == 0.5  # only kp2's quote is inside a retrieved text


def test_miss_and_wrong_passage():
    r = fa._good(LOCKE)
    g = grade(HOBBES, r)
    assert not g["block_hit"] and g["block_rank"] is None and g["evidence_recall"] == 0.0 and not g["cited_block"]


def test_near_hit_same_chapter_and_section():
    r = fa._good(LOCKE)
    r["retrieved"][0].update(passage_id="pg7370:main:other:c0", block_id="pg7370:main:other", text="unrelated words here")
    g = grade(LOCKE, r)
    assert not g["block_hit"] and g["near_hit"] is True
    r["retrieved"][0]["section"] = 28
    assert grade(LOCKE, r)["near_hit"] is False
    # anchors without chapter/section never compute it
    r2 = fa._good(BURKE)
    r2["retrieved"][0]["text"] = "nothing"
    r2["retrieved"][0]["block_id"] = "x"
    assert grade(BURKE, r2)["near_hit"] is None


def test_invalid_ids_and_m5():
    r = fa._good(LOCKE)
    r["citations"][0]["passage_id"] = "bogus:id:c0"
    g = grade(LOCKE, r)
    assert g["invalid_ids"] == ["bogus:id:c0"] and g["quotes_verified"]["verified"] == 2 and g["quotes_verified"]["total"] == 3


def test_quote_not_in_cited_passage_is_unverified():
    r = fa._good(LOCKE)
    r["citations"][1]["quote"] = "this was never written anywhere in the text"
    g = grade(LOCKE, r)
    assert g["quotes_verified"]["verified"] == 2 and g["invalid_ids"] == []


def test_label_mismatch_by_skeleton():
    r = fa._good(LOCKE)
    r["citations"][0]["locator"] = "BOOK ii, chapter 5, §27, paragraph 3 (edition-specific)"   # case only: fine
    assert grade(LOCKE, r)["label_mismatches"] == []
    r["citations"][0]["locator"] = "Book II, Chapter 6, §30"
    r["citations"][1]["author"] = "Thomas Hobbes"
    m = grade(LOCKE, r)["label_mismatches"]
    assert [x["fields"] for x in m] == [["locator"], ["author"]]


def test_trivial_quotes_use_configured_minimum():
    r = fa._good(LOCKE)
    r["citations"][0]["quote"] = "every man"
    assert grade(LOCKE, r)["trivial_quotes"] == 1
    assert grade(LOCKE, r, quote_min_words=2)["trivial_quotes"] == 0


@pytest.mark.parametrize("declined,expected", [(None, True), (False, True), (True, False)])
def test_zero_citations(declined, expected):
    r = fa._good(LOCKE)
    r["citations"], r["declined"] = [], declined
    assert grade(LOCKE, r)["no_citations"] is expected


def test_zero_citations_for_false_premise_card_is_not_m9():
    fp = BY_AUTHOR["John Lockefalse_premise"]
    r = fa._good(fp)
    r["citations"] = []
    assert grade(fp, r)["no_citations"] is False


def test_finalize_declined_after_j4():
    r = fa._good(LOCKE)
    r["citations"] = []
    g = grade(LOCKE, r)
    card = Card.model_validate(LOCKE)
    assert g["no_citations"] is True
    mech.finalize_declined(card, g, True)
    assert g["no_citations"] is False and g["declined"] is True


def test_self_check_disagreement():
    r = fa._good(LOCKE)
    r["citations"][0]["quote"] = "words that are not in the passage at all"
    r["self_check"][0]["quote"] = r["citations"][0]["quote"]  # Agora says ok; we say no
    r["self_check"][1]["status"] = "not_found"
    g = grade(LOCKE, r)
    assert len(g["self_check_disagreements"]) == 1
    assert g["self_check_disagreements"][0]["quote"].startswith("words that")


def test_declined_taken_from_result():
    r = fa._good(LOCKE)
    r["declined"] = True
    assert grade(LOCKE, r)["declined"] is True


def test_never_retrieved_warning():
    results = [validate_result(fa._good(LOCKE))]
    works = ["Second Treatise of Government", "Leviathan", "On Liberty"]
    assert mech.never_retrieved(works, results) == ["Leviathan", "On Liberty"]
    assert mech.never_retrieved(works, [None]) == sorted(works)
