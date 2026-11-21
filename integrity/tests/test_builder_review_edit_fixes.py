"""Review-edit path: HC11 uniqueness (M3), passage cards cannot gain a premise, strict --batch ids."""

import json

import pytest

from integrity.builder import review
from integrity.builder.handlers_sheet import cmd_review
from integrity.common.settings import load_settings
from integrity.tests.builder_review_helpers import (
    SECT_27,
    locke_corpus,
    make_real_card,
    scripted,
    write_batch,
)

B1 = "b-20261121-101500-s7"
DUP_QUOTE = "The labour of his body, and the work of his hands"  # also copied into another paragraph below


@pytest.fixture
def settings():
    return load_settings()


def go(settings, *lines, edit_fn, loader):
    out: list[str] = []
    res = review.run_review(settings, None, input_fn=scripted(*lines), output_fn=out.append, edit_fn=edit_fn,
                            now=lambda: "t", corpus_loader=loader)
    return res, "\n".join(out)


def set_kp2(quote):
    def fn(text):
        d = json.loads(text)
        d["key_points"][1]["quote"] = quote
        return json.dumps(d)
    return fn


def test_edit_to_a_quote_that_is_not_unique_is_refused_hc11(settings):
    write_batch(settings.data_dir, B1, [make_real_card("27")])
    def corpus():
        return locke_corpus("A later paragraph that repeats: " + DUP_QUOTE + ", we may say, are properly his.")

    _res, out = go(settings, "e", "a", "q", edit_fn=set_kp2(DUP_QUOTE), loader=corpus)
    assert "HC11" in out and "FAILS validation" in out and "Cannot approve" in out
    c = review.load_batch_cards(settings.data_dir, B1)[0]
    assert c.review.status == "pending" and "uniqueness_unchecked" not in c.flags


def test_edit_to_a_unique_quote_passes_and_corpus_loaded_once(settings):
    write_batch(settings.data_dir, B1, [make_real_card("27")])
    loads = []

    def loader():
        loads.append(1)
        return locke_corpus()

    calls = []

    def edit(text):
        calls.append(1)
        return set_kp2(DUP_QUOTE)(text)

    res, out = go(settings, "e", "e", "a", edit_fn=edit, loader=loader)
    assert len(calls) == 2 and loads == [1]  # two edits, one (cached) corpus load
    assert res.approved == 1 and "HC11" not in out


def test_corpus_load_failure_allows_edit_with_warning_and_flag(settings):
    write_batch(settings.data_dir, B1, [make_real_card("27")])

    def broken():
        raise RuntimeError("provider exploded")

    _res, out = go(settings, "e", "a", edit_fn=set_kp2(DUP_QUOTE), loader=broken)
    assert "WARNING" in out and "NOT checked" in out and "provider exploded" in out
    c = review.load_batch_cards(settings.data_dir, B1)[0]
    assert c.flags.count("uniqueness_unchecked") == 1 and c.review.status == "approved"


def test_passage_card_cannot_gain_a_premise(settings):
    card = make_real_card("27")
    edited = json.loads(json.dumps(review.editable_fields(card)))
    edited["premise"] = "Locke thinks property is a gift from the king."
    with pytest.raises(ValueError, match="no premise"):
        review.apply_edit(card, edited)
    write_batch(settings.data_dir, B1, [card])

    def fn(text):
        d = json.loads(text)
        d["premise"] = "sneaky"
        return json.dumps(d)

    _res, out = go(settings, "e", "q", edit_fn=fn, loader=locke_corpus)
    assert "Edit not applied" in out
    assert review.load_batch_cards(settings.data_dir, B1)[0].premise is None


def test_false_premise_card_keeps_editable_premise():
    card = make_real_card("27").model_copy(update={"type": "false_premise", "premise": "p"})
    d = review.editable_fields(card)
    d["premise"] = "new premise"
    assert review.apply_edit(card, d).premise == "new premise"
    assert SECT_27  # helper import is used


@pytest.mark.parametrize("bad", ["../../etc", "b-1", "b-20261121-101500-s7/../x", "B-20261121-101500-s7",
                                 "b-20261121-101500-s7\n", "b-20261121-101500-sX"])
def test_batch_id_is_validated(settings, bad):
    with pytest.raises(review.ReviewError) as e:
        review.pick_batch(settings.data_dir, bad)
    assert e.value.exit_code == 1 and "invalid batch id" in str(e.value)


def test_cmd_review_rejects_bad_batch_with_exit_1(settings, capsys):
    import argparse

    assert cmd_review(argparse.Namespace(batch="../../x"), settings) == 1
    assert "invalid batch id" in capsys.readouterr().err
