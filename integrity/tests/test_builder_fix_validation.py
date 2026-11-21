"""Regression tests for the validation fixes: HC11, SF10, HC9 whole word, pending-retirement self-healing,
corrupt batch files, file modes, usage errors, SF3 cues."""

import argparse
import os
import stat

import pytest

from integrity.builder import checks as K
from integrity.builder import publish as pub
from integrity.builder import review as rv
from integrity.builder.attribution import cue_phrases
from integrity.builder.build import run_build
from integrity.builder.card_validation import validate_card
from integrity.builder.corpus import QuoteIndex
from integrity.builder.drafter import DraftCard
from integrity.builder.handlers import cmd_build
from integrity.builder.handlers_sheet import cmd_publish, cmd_review
from integrity.common import storage
from integrity.common.settings import load_settings
from integrity.tests import builder_helpers as H
from integrity.tests.builder_review_helpers import make_real_card, write_batch

SETTINGS = load_settings()
B1, B2, B3 = "b-20261121-101500-s7", "b-20261122-101500-s8", "b-20261123-101500-s9"


@pytest.fixture
def settings():
    return load_settings()


def approved(key, batch=B1, **kw):
    return make_real_card(key, status="approved", batch_id=batch, **kw)


# ----------------------------------------------------------------------------- finding 6


def test_pending_retirement_already_retired_is_dropped_after_crash(settings, capsys):
    c27, c26 = approved("27"), approved("26", B2)
    write_batch(settings.data_dir, B1, [c27])
    pub.publish(settings)
    write_batch(settings.data_dir, B2, [c26])
    pub.stage_retirement(settings, c27.card_id, "wrong")
    pub.publish(settings)  # v002 retires c27 and clears pending
    # simulate the crash: the sheet was written but pending_retirements.json was not cleared
    storage.atomic_write_json(pub.pending_retirements_path(settings.data_dir),
                              [{"card_id": c27.card_id, "reason": "wrong", "staged_at": "x"}])
    c_new = make_real_card("27", status="approved", batch_id=B3, question="Why does Locke think labour makes property?")
    write_batch(settings.data_dir, B3, [c_new])
    r = pub.publish(settings)
    assert r.version == "v003" and r.retired == []
    assert "already retired" in capsys.readouterr().out
    assert pub.read_pending_retirements(settings.data_dir) == []


def test_pending_retirement_of_never_published_card_still_errors(settings):
    write_batch(settings.data_dir, B1, [approved("27")])
    pub.publish(settings)
    write_batch(settings.data_dir, B2, [approved("26", B2)])
    storage.atomic_write_json(pub.pending_retirements_path(settings.data_dir),
                              [{"card_id": "c-neverexisted", "reason": "x"}])
    with pytest.raises(pub.PublishError, match="not in the latest sheet"):
        pub.publish(settings)


# ----------------------------------------------------------------------------- finding 7 (HC11)

TEXT = H.prose(21, 14)
TOK = TEXT.split()
Q1, Q2 = " ".join(TOK[3:11]), " ".join(TOK[30:38])


def _draft(q1=Q1, q2=Q2):
    return DraftCard.model_validate({
        "status": "ok", "unsuitable_reason": None, "question": "What does Locke say about this matter?",
        "key_points": [{"statement": "a", "quote": q1, "speaker": "author_sincere"},
                       {"statement": "b", "quote": q2, "speaker": "author_sincere"}]})


def test_hc11_quote_in_two_paragraphs_of_the_work_fails():
    p = H.mkpara(TEXT, position=0)
    other = H.mkpara("Elsewhere we read " + Q1 + " again.", position=1)
    idx = QuoteIndex([p, other])
    res = K.run_hard_checks(_draft(), p, SETTINGS, "passage", idx)
    assert [f.check for f in res.failures] == ["HC11"] and "kp1" in res.failures[0].detail


def test_hc11_unique_quote_passes_and_other_work_does_not_count():
    p = H.mkpara(TEXT, position=0)
    other_work = H.mkpara("Elsewhere we read " + Q1 + " again.", position=0, work_id="w9:main")
    idx = QuoteIndex([p, other_work])
    assert K.run_hard_checks(_draft(), p, SETTINGS, "passage", idx).ok
    assert K.run_hard_checks(_draft(), p, SETTINGS, "passage").ok  # no index: HC11 not evaluated


def test_hc11_in_card_validation_with_corpus_param():
    p = H.mkpara(TEXT, position=0)
    card = make_real_card("27")
    other = H.mkpara("zz " + card.key_points[0].quote + " zz", position=3, work_id=card.anchor.work_id)
    me = H.mkpara(card.anchor.text, position=2, work_id=card.anchor.work_id)
    rules = SETTINGS.author_rules("John Locke")
    assert validate_card(card, rules) == []
    assert validate_card(card, rules, QuoteIndex([me])) == []
    fails = validate_card(card, rules, QuoteIndex([me, other]))
    assert [f.check for f in fails] == ["HC11"]
    assert p  # silence


def test_build_discards_hc11_and_redraws():
    corpus = H.fake_corpus(30)
    dup = []
    for i, p in enumerate(corpus.paragraphs):
        if p.author == "John Locke":
            q = H.mkpara(p.text, work_id=p.work_id, block_id=p.block_id + ":dup", position=1000 + i,
                         author=p.author, work=p.work)
            dup.append(q)
    assert dup
    corpus.paragraphs.extend(dup)
    s = run_build(load_settings(), count=4, authors=["Locke"], seed=7, corpus=corpus,
                  drafter_client=H.ScriptedClient(lambda c, i: H.good_draft(c, i)),
                  attribution_client=H.ScriptedClient(H.advisory_ok))
    assert s.discarded_by_reason.get("HC11", 0) > 0 and s.filled == 0


def test_quote_min_words_default_is_six():
    assert SETTINGS.checks.quote_min_words == 6


# ----------------------------------------------------------------------------- SF10, HC9, SF3


def test_sf10_duplicate_question_flag():
    p = H.mkpara(TEXT)
    kps = K.run_hard_checks(_draft(), p, SETTINGS).key_points
    from integrity.common import textnorm
    seen = {textnorm.skeleton("What does Locke say about this matter?")}
    assert "duplicate_question" in K.soft_flags("what does Locke say about this matter?", kps, p, SETTINGS, seen)
    assert "duplicate_question" not in K.soft_flags("Another question?", kps, p, SETTINGS, seen)


def test_sf10_in_build_against_batch_and_published(settings):
    corpus = H.fake_corpus(30)
    s = run_build(settings, count=4, authors=["Locke"], seed=7, corpus=corpus,
                  drafter_client=H.ScriptedClient(lambda c, i: H.good_draft(c, i)),
                  attribution_client=H.ScriptedClient(H.advisory_ok))
    cards = rv.load_batch_cards(settings.data_dir, s.batch_id)
    assert len(cards) >= 2
    assert "duplicate_question" not in cards[0].flags
    assert all("duplicate_question" in c.flags for c in cards[1:])


def test_hc9_surname_is_a_whole_word():
    p = H.mkpara(TEXT, author="John Stuart Mill")
    d = _draft().model_copy(update={"question": "How many million people does the state serve?"})
    assert "HC9" in {f.check for f in K.run_hard_checks(d, p, SETTINGS).failures}
    d2 = d.model_copy(update={"question": "What does MILL say about liberty?"})
    assert "HC9" not in {f.check for f in K.run_hard_checks(d2, p, SETTINGS).failures}
    card = make_real_card("27", question="How many million men does the state serve?")
    card.anchor.author = "John Stuart Mill"
    assert any(f.check == "HC9" for f in validate_card(card, SETTINGS.author_rules("John Stuart Mill")))


@pytest.mark.parametrize("phrase", ["perhaps may doubt", "may be objected", "objectors", "it may be asked",
                                    "will be said", "it is said"])
def test_sf3_objection_cues(phrase):
    text = f"Some objectors, and {phrase} that this is so, will press the point."
    assert any(phrase in c for c in cue_phrases(text, "John Stuart Mill"))


# ----------------------------------------------------------------------------- corrupt files, modes


def test_corrupt_cards_jsonl_gives_one_line_error(settings, capsys):
    d = write_batch(settings.data_dir, B1, [approved("27")])
    (d / "cards.jsonl").write_text('{"card_id": "c-1", "ques', encoding="utf-8")
    assert cmd_publish(argparse.Namespace(note=""), settings) == 1
    assert cmd_review(argparse.Namespace(batch=None), settings) == 1
    err = capsys.readouterr().err
    assert "corrupt" in err and "Traceback" not in err and len(err.strip().splitlines()) == 2


def test_corrupt_pending_retirements_gives_error(settings):
    write_batch(settings.data_dir, B1, [approved("27")])
    pub.publish(settings)
    pub.pending_retirements_path(settings.data_dir).write_text("[{", encoding="utf-8")
    with pytest.raises(pub.PublishError, match="corrupt"):
        pub.publish(settings)


def test_changelog_and_pending_modes_are_0644(settings):
    c27 = approved("27")
    write_batch(settings.data_dir, B1, [c27])
    pub.publish(settings)
    pub.stage_retirement(settings, c27.card_id, "r")
    for f in ("CHANGELOG.md", "pending_retirements.json"):
        assert stat.S_IMODE(os.stat(settings.data_dir / "sheets" / f).st_mode) == 0o644


# ----------------------------------------------------------------------------- usage errors


@pytest.mark.parametrize("flags", [["--count", "-1"], ["--count", "201"], ["--false-premise", "-1"],
                                   ["--false-premise", "51"]])
def test_build_count_bounds_are_usage_errors(settings, flags, capsys):
    ns = argparse.Namespace(count=None, false_premise=None, source=None, author=None, seed=1, dry_run=True)
    for k, v in zip(flags[::2], flags[1::2]):
        setattr(ns, k[2:].replace("-", "_"), int(v))
    assert cmd_build(ns, settings) == 1
    assert "must be between" in capsys.readouterr().err


def test_unknown_source_is_usage_error_listing_valid_names(settings, capsys):
    ns = argparse.Namespace(count=1, false_premise=0, source=["nope.epub"], author=None, seed=1, dry_run=True)
    assert cmd_build(ns, settings) == 1
    err = capsys.readouterr().err
    assert "unknown source" in err and ".epub" in err.split("valid sources:")[1]
