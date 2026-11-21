import json

import pytest
from pydantic import ValidationError

from integrity.common import schema as sc
from integrity.tests.helpers import make_card


def test_canonical_json_and_hash():
    assert sc.canonical_json({"b": 1, "a": "é"}) == '{"a":"é","b":1}'
    assert sc.canonical_sha256({"a": 1, "b": 2}) == sc.canonical_sha256({"b": 2, "a": 1})
    assert sc.sha256_hex("abc") == sc.sha256_hex(b"abc")


def test_card_id_formula():
    cid = sc.make_card_id("b", "passage", "q?")
    assert cid == "c-" + sc.sha256_hex("b\npassage\nq?")[:10] and len(cid) == 12


def test_card_roundtrip_and_int_coercion():
    card = sc.Card.model_validate(make_card())
    assert card.anchor.chapter == 5 and isinstance(card.anchor.chapter, int)
    again = sc.Card.model_validate(json.loads(json.dumps(sc.dump(card))))
    assert again == card
    assert sc.canonical_sha256(sc.dump(again)) == sc.canonical_sha256(sc.dump(card))


def test_card_defaults_and_extras_kept():
    d = make_card()
    for k in ("premise", "holdout", "flags", "provenance", "review", "expected_behavior"):
        d.pop(k)
    d["future_field"] = {"x": 1}
    card = sc.Card.model_validate(d)
    assert card.review.status == "pending" and card.holdout is False
    assert sc.dump(card)["future_field"] == {"x": 1}


def test_card_rejects_bad_enums():
    with pytest.raises(ValidationError):
        sc.Card.model_validate(make_card(type="weird"))
    with pytest.raises(ValidationError):
        sc.Card.model_validate(make_card(review={"status": "maybe"}))


def test_sheet_roundtrip_counts_hash():
    cards = [make_card(), make_card(card_id="c-zzz", holdout=True, type="false_premise")]
    models = [sc.Card.model_validate(c) for c in cards]
    counts = sc.compute_counts(models)
    assert (counts.cards, counts.holdout) == (2, 1)
    assert counts.by_author == {"John Locke": 2} and counts.by_type == {"passage": 1, "false_premise": 1}
    retired = [{"card_id": "c-1", "reason": "r"}]
    h = sc.content_sha256(models, version="v001", retired=retired)
    assert h == sc.content_sha256([sc.dump(m) for m in models], version="v001", retired=retired)
    assert h != sc.content_sha256(models, version="v002", retired=retired)  # version, parent, retired are hashed
    assert h != sc.content_sha256(models, version="v001", retired=[])
    assert h != sc.content_sha256(models, version="v001", parent="v000", retired=retired)
    sheet = sc.Sheet(version="v001", counts=counts, cards=models, content_sha256=h, retired=retired)
    back = sc.Sheet.model_validate_json(sheet.model_dump_json())
    assert back == sheet and back.schema_version == 1 and back.textnorm_version == 1


def test_batch_run_records_roundtrip():
    b = sc.BatchRecord(batch_id="b-20261121-101500-s7", seed=7,
                       slots=[sc.SlotPlanEntry(slot="locke-treatise#2", stratum="s", bin=0)])
    assert sc.BatchRecord.model_validate(sc.dump(b)) == b
    d = sc.DiscardedDraft(slot="x", failed_checks=[sc.CheckFailure(check="HC4", detail="d")], raw_output={"a": 1})
    assert sc.DiscardedDraft.model_validate(sc.dump(d)) == d
    r = sc.RunRecord(run_id="r-20261121-101500", sheet_version="v001")
    assert sc.RunRecord.model_validate(sc.dump(r)) == r
    raw = sc.RawRecord(card_id="c", error=sc.RawError(type="contract_violation", message="m"))
    assert sc.RawRecord.model_validate(sc.dump(raw)) == raw
    g = sc.GradeRecord(card_id="c", judge_calls=[sc.JudgeCall(prompt_id="p", evidence_ok=True)])
    assert sc.GradeRecord.model_validate(sc.dump(g)) == g
    assert sc.RunIndexEntry(run_id="r").headline == {}


def test_agora_result_contract():
    res = sc.AgoraResult.model_validate({
        "answer": "a (Locke, T, 1)",
        "citations": [{"passage_id": "p1", "author": "A", "work": "W", "locator": "L", "quote": "q", "chapter": 2.0}],
        "retrieved": [{"passage_id": "p1", "text": "t", "author": "A", "work": "W", "locator": "L", "section": 3.0},
                      {"passage_id": "p2", "text": "t", "author": "A", "work": "W", "locator": "L", "rank": 7}],
        "attempts": 2.0, "info": {"model": "m"}, "unexpected": 1,
    })
    assert res.citations[0].chapter == 2 and isinstance(res.citations[0].chapter, int)
    assert [r.rank for r in res.retrieved] == [1, 7]
    assert res.retrieved[0].section == 3 and res.attempts == 2 and res.declined is None
    assert res.model_dump()["unexpected"] == 1


def test_agora_result_missing_required_fails():
    with pytest.raises(ValidationError):
        sc.AgoraResult.model_validate({"answer": "a", "citations": []})


def test_retrieved_rank_must_be_positive():
    import pydantic

    base = {"passage_id": "p", "text": "t", "author": "a", "work": "w", "locator": "l"}
    for bad in (0, -1):
        with pytest.raises(pydantic.ValidationError):
            sc.RetrievedItem(**base, rank=bad)
        with pytest.raises(pydantic.ValidationError):
            sc.AgoraResult(answer="x", citations=[], retrieved=[dict(base, rank=bad)])
    assert sc.RetrievedItem(**base, rank=1).rank == 1
    assert sc.AgoraResult(answer="x", citations=[], retrieved=[base]).retrieved[0].rank == 1
