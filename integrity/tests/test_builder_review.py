import json

import pytest

from integrity.builder import review
from integrity.builder.card_validation import make_validator, validate_card
from integrity.common import storage
from integrity.common.settings import load_settings
from integrity.tests.builder_review_helpers import (
    SECT_27,
    locke_corpus,
    make_real_card,
    scripted,
    write_batch,
)

B1 = "b-20261121-101500-s7"


@pytest.fixture
def settings():
    return load_settings()


def run(settings, *lines, edit_fn=None, color=False, batch=None, corpus_loader=locke_corpus):
    out: list[str] = []
    res = review.run_review(settings, batch, input_fn=scripted(*lines), output_fn=out.append, color=color,
                            edit_fn=edit_fn, now=lambda: "2026-11-21T11:00:00Z", corpus_loader=corpus_loader)
    return res, "\n".join(out)


def status(settings, batch=B1):
    return [c.review.status for c in review.load_batch_cards(settings.data_dir, batch)]


def two(settings):
    write_batch(settings.data_dir, B1, [make_real_card("27"), make_real_card("26")])


def test_screen_layout_no_colour(settings):
    two(settings)
    _, out = run(settings, "q")
    assert "[1/2]  John Locke" in out and "FLAGS" in out and "split_paragraph" in out
    assert "⟦every man has a property in his own person⟧" in out
    assert "\x1b[" not in out
    assert "✓ verified" in out and "kp1 author_sincere" in out
    assert "[a]pprove  [e]dit  [r]eject  [s]kip  [?] checklist  [q]uit" in out
    assert "CONTEXT BEFORE" in out and "CONTEXT AFTER" in out


def test_screen_colour(settings):
    two(settings)
    _, out = run(settings, "q", color=True)
    assert "\x1b[1mevery man has a property in his own person\x1b[0m" in out
    assert "\x1b[2m" in out and "⟦" not in out


def test_approve_reject_skip_and_progress_saved(settings):
    write_batch(settings.data_dir, B1, [make_real_card("27"), make_real_card("26")])
    res, _ = run(settings, "a", "r", "2")
    assert (res.approved, res.rejected, res.pending) == (1, 1, 0)
    cards = review.load_batch_cards(settings.data_dir, B1)
    assert cards[0].review.status == "approved" and cards[0].review.reviewed_at == "2026-11-21T11:00:00Z"
    assert cards[1].review.reject_reason == "wrong key point"


def test_skip_leaves_pending_and_quit_resume(settings):
    write_batch(settings.data_dir, B1, [make_real_card("27"), make_real_card("26")])
    res, _ = run(settings, "s", "q")
    assert res.skipped == 1 and res.quit and status(settings) == ["pending", "pending"]
    # approve first then quit: resume starts at the second card
    run(settings, "a", "q")
    assert status(settings) == ["approved", "pending"]
    _, out = run(settings, "q")
    assert "[2/2]" in out and "[1/2]" not in out


def test_eof_is_quit_and_saves(settings):
    two(settings)
    res, _ = run(settings, "a")
    assert res.quit and status(settings) == ["approved", "pending"]


def test_checklist_and_unknown(settings):
    two(settings)
    _, out = run(settings, "?", "zzz", "q")
    assert "Can the question be answered from this paragraph alone?" in out and "Unrecognised command" in out


def test_reject_reason_menu_other_and_cancel(settings):
    two(settings)
    _res, _ = run(settings, "r", "", "r", "6", "too fiddly", "q")  # blank cancels; 6 = other
    cards = review.load_batch_cards(settings.data_dir, B1)
    assert cards[0].review.reject_reason == "other: too fiddly"
    _res2, _ = run(settings, "r", "my own words", "q")
    assert review.load_batch_cards(settings.data_dir, B1)[1].review.reject_reason == "other: my own words"


@pytest.mark.parametrize("n,reason", list(enumerate(review.REJECT_REASONS, 1)))
def test_reject_menu_reasons(settings, n, reason):
    write_batch(settings.data_dir, B1, [make_real_card("27")])
    run(settings, "r", str(n))
    assert review.load_batch_cards(settings.data_dir, B1)[0].review.reject_reason == reason


def _editor(mutate):
    def fn(text):
        d = json.loads(text)
        mutate(d)
        return json.dumps(d)
    return fn


def test_edit_pass_recomputes_spans_and_preserves_original(settings):
    write_batch(settings.data_dir, B1, [make_real_card("27")])
    orig_q = make_real_card("27").question

    def mut(d):
        d["question"] = "What does Locke say makes labour the ground of property?"
        d["key_points"][0]["quote"] = "Every man has a PROPERTY in his own person,"  # case/punctuation differences
        d["key_points"][0]["statement"] = "People own themselves."

    _res, out = run(settings, "e", "a", edit_fn=_editor(mut))
    c = review.load_batch_cards(settings.data_dir, B1)[0]
    assert "passes validation" in out
    assert c.review.status == "approved" and c.review.edited
    assert c.review.original["question"] == orig_q
    kp = c.key_points[0]
    assert kp.quote == "every man has a property in his own person"  # source text, not typed text
    assert SECT_27[kp.span[0]:kp.span[1]] == kp.quote and kp.chunk_ids == [c.anchor.chunks[0].passage_id]
    assert c.card_id == make_real_card("27").card_id  # id never changes


def test_edit_fail_cannot_be_approved(settings):
    write_batch(settings.data_dir, B1, [make_real_card("27")])

    def mut(d):
        d["key_points"][1]["quote"] = "he hath mixed his sweat with the soil"

    _res, out = run(settings, "e", "a", "q", edit_fn=_editor(mut))
    assert "FAILS validation" in out and "HC4" in out and "Cannot approve" in out
    c = review.load_batch_cards(settings.data_dir, B1)[0]
    assert c.review.status == "pending" and c.review.edited and c.review.original is not None
    assert c.key_points[1].quote == "he hath mixed his sweat with the soil"


def test_edit_then_fix_then_approve(settings):
    write_batch(settings.data_dir, B1, [make_real_card("27")])
    calls = []

    def fn(text):
        d = json.loads(text)
        calls.append(json.loads(text))
        d["key_points"][1]["quote"] = ("bad quote that is absent from the text" if len(calls) == 1
                                       else "he hath mixed his labour with, and joined to it something that is his own")
        return json.dumps(d)

    res, _out = run(settings, "e", "e", "a", edit_fn=fn)
    assert res.approved == 1
    assert calls[1]["key_points"][1]["quote"] == "bad quote that is absent from the text"  # editor shows current edits


def test_edit_garbage_json_keeps_card(settings):
    write_batch(settings.data_dir, B1, [make_real_card("27")])
    _res, out = run(settings, "e", "q", edit_fn=lambda t: "{not json")
    assert "Edit not applied" in out
    c = review.load_batch_cards(settings.data_dir, B1)[0]
    assert not c.review.edited and c.review.original is None


def test_edit_question_without_question_mark_fails(settings):
    write_batch(settings.data_dir, B1, [make_real_card("27")])
    _, out = run(settings, "e", "q", edit_fn=_editor(lambda d: d.update(question="Tell me about Locke.")))
    assert "HC2" in out


def test_lock_prevents_two_reviewers(settings):
    two(settings)
    lock = storage.FileLock(storage.batch_lock_path(settings.data_dir, B1))
    lock.acquire()
    try:
        with pytest.raises(review.ReviewLocked):
            run(settings, "q")
    finally:
        lock.release()
    run(settings, "q")  # released: works again
    assert not storage.batch_lock_path(settings.data_dir, B1).exists()


def test_stale_lock_taken_over(settings):
    two(settings)
    lock_path = storage.batch_lock_path(settings.data_dir, B1)
    lock_path.write_text("999999999\n")
    assert storage.FileLock(lock_path).is_stale()
    res, out = run(settings, "s")  # no ReviewLocked: the dead owner's lock was taken over
    assert res.skipped == 1 and "[1/2]" in out
    assert not lock_path.exists()  # and released again at the end


def test_batch_selection(settings):
    d = settings.data_dir
    with pytest.raises(review.NoPendingBatch, match="no pending batch"):
        run(settings, "q")
    write_batch(d, "b-20261101-000000-s1", [make_real_card("27", status="approved")])
    write_batch(d, "b-20261102-000000-s2", [make_real_card("26")])
    write_batch(d, "b-20261103-000000-s3", [make_real_card("27", status="rejected")])
    res, _ = run(settings, "q")
    assert res.batch_id == "b-20261102-000000-s2"
    with pytest.raises(review.NoPendingBatch):
        run(settings, "q", batch="b-20261101-000000-s1")
    with pytest.raises(review.NoPendingBatch):
        run(settings, "q", batch="b-20261101-000000-s2")


def test_validator_default_accepts_real_card_and_flags_problems(settings):
    v = make_validator(settings)
    good = make_real_card("27")
    assert v(good) == []
    bad = good.model_copy(deep=True)
    bad.question = "How is property acquired?"  # no surname
    bad.key_points[1].span = [0, 5]
    bad.key_points[2].quote = "at least where"  # too few words
    checks = {f.check for f in v(bad)}
    assert {"HC9", "HC4", "HC5"} <= checks


def test_validator_hc3_hc6_hc7_hc10(settings):
    v = make_validator(settings)
    c = make_real_card("26")
    c3 = c.model_copy(deep=True)
    c3.key_points.append(c3.key_points[0].model_copy(update={"id": "kp3"}))
    assert {"HC3", "HC7"} <= {f.check for f in v(c3)}
    c6 = c.model_copy(deep=True)
    c6.key_points[0].chunk_ids = ["nope"]
    assert "HC6" in {f.check for f in v(c6)}
    c10 = make_real_card("27")
    c10.anchor.text = c10.anchor.text.replace("every man has a property in his own person",
                                              "“every man has a property in his own person”")
    # spans shift by two characters: recompute through apply_edit
    edited = review.apply_edit(c10, review.editable_fields(c10))
    rules = settings.author_rules("John Locke") | {"quoted_text_is_other_speaker": True}
    assert any(f.check == "HC10" for f in validate_card(edited, rules))
    assert not any(f.check == "HC10" for f in validate_card(edited, settings.author_rules("John Locke")))
