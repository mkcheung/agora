"""Hard checks HC1-HC10, soft flags SF1-SF9 and attribution cues."""

import pytest

from integrity.builder import attribution as A
from integrity.builder import checks as K
from integrity.builder.drafter import DraftCard, FalsePremiseDraft
from integrity.common.settings import load_settings
from integrity.tests.builder_helpers import ScriptedClient, mkpara, prose

SETTINGS = load_settings()
TEXT = prose(21, 14)
TOK = TEXT.split()
Q1, Q2 = " ".join(TOK[3:11]), " ".join(TOK[30:38])


def draft(**over):
    d = {
        "status": "ok", "unsuitable_reason": None, "question": "What does Locke say about this matter?",
        "key_points": [{"statement": "a", "quote": Q1, "speaker": "author_sincere"},
                       {"statement": "b", "quote": Q2, "speaker": "author_sincere"}],
    }
    d.update(over)
    return DraftCard.model_validate(d)


def kp(quote, speaker="author_sincere", statement="s"):
    return {"statement": statement, "quote": quote, "speaker": speaker}


def failing(d, p=None, kind="passage", settings=SETTINGS):
    p = p or mkpara(TEXT)
    return {f.check for f in K.run_hard_checks(d, p, settings, kind).failures}


def test_clean_draft_passes_and_fills_spans_and_chunk_ids():
    p = mkpara(TEXT)
    res = K.run_hard_checks(draft(), p, SETTINGS)
    assert res.ok
    k1 = res.key_points[0]
    assert TEXT[k1.span[0]:k1.span[1]] == k1.quote == Q1 and k1.quote_model == Q1
    assert k1.chunk_ids == [p.chunks[0][0]] and k1.id == "kp1"


def test_source_span_replaces_model_quote_text():
    p = mkpara(TEXT)
    sloppy = Q1.upper().replace(" ", "  ")
    res = K.run_hard_checks(draft(key_points=[kp(sloppy), kp(Q2)]), p, SETTINGS)
    assert res.ok and res.key_points[0].quote == Q1 and res.key_points[0].quote_model == sloppy


def test_hc1_unsuitable_reason():
    res = K.run_hard_checks(draft(status="unsuitable", unsuitable_reason="ironic"), mkpara(TEXT), SETTINGS)
    assert [(f.check, f.detail) for f in res.failures] == [("HC1", "unsuitable:ironic")]


@pytest.mark.parametrize("q", ["", "What does Locke say", "What does Locke say" + " x" * 200 + "?"])
def test_hc2_question(q):
    assert "HC2" in failing(draft(question=q))


def test_hc2_false_premise_needs_premise():
    d = FalsePremiseDraft.model_validate({**draft().model_dump(), "premise": " "})
    assert "HC2" in failing(d, kind="false_premise")
    d2 = FalsePremiseDraft.model_validate({**draft().model_dump(), "premise": "Locke says X."})
    assert failing(d2, kind="false_premise") == set()


def test_hc3_counts():
    assert "HC3" in failing(draft(key_points=[kp(Q1)]))
    three = [kp(Q1), kp(Q2), kp(" ".join(TOK[60:68]))]
    assert "HC3" in failing(draft(key_points=three), mkpara(TEXT[:700] + " " + " ".join(TOK[60:68])))
    assert "HC3" not in failing(draft(key_points=three), mkpara(TEXT))


def test_hc4_quote_not_in_paragraph_or_only_in_context():
    ctx = mkpara(TEXT, context_before="Something entirely different appears only in context here ok.")
    d = draft(key_points=[kp("Something entirely different appears only in context here"), kp(Q2)])
    assert "HC4" in failing(d, ctx)
    assert "HC4" in failing(draft(key_points=[kp(Q1 + " extra"), kp(Q2)]))
    assert "HC4" in failing(draft(key_points=[kp(Q1[:-1] + "e"), kp(Q2)]))  # no modernising / altering letters
    assert "HC4" in failing(draft(key_points=[kp(Q1[:20] + "..." + Q1[-10:]), kp(Q2)]))


def test_hc5_word_limits():
    short = " ".join(TOK[3:6])
    assert len(TOK) >= 100  # the fixture must be long enough for the boundary cases below
    assert "HC5" in failing(draft(key_points=[kp(short), kp(Q2)]))
    # the hard limit is 40 words (the real drafting model overshoots 25): 41 fails, 40 passes
    at_limit = " ".join(TOK[3:43])
    over = " ".join(TOK[3:44])
    assert len(at_limit.split()) == 40 and len(over.split()) == 41
    assert "HC5" in failing(draft(key_points=[kp(over), kp(Q2)]))
    assert "HC5" not in failing(draft(key_points=[kp(at_limit), kp(Q2)]))


def test_hc6_quote_spanning_two_chunks_fails():
    a, b = prose(31, 6), prose(32, 6)
    text = a + " " + b
    p = mkpara(text, chunks=[("x:c0", a), ("x:c1", b)])
    seam = " ".join(a.split()[-4:] + b.split()[:4])
    d = draft(key_points=[kp(seam), kp(" ".join(b.split()[20:28]))])
    assert "HC6" in failing(d, p)
    ok = draft(key_points=[kp(" ".join(a.split()[3:11])), kp(" ".join(b.split()[20:28]))])
    res = K.run_hard_checks(ok, p, SETTINGS)
    assert res.ok and res.key_points[0].chunk_ids == ["x:c0"] and res.key_points[1].chunk_ids == ["x:c1"]


def test_hc7_duplicate_and_overlapping_spans():
    assert "HC7" in failing(draft(key_points=[kp(Q1), kp(Q1)]))
    overlap = " ".join(TOK[8:16])
    assert "HC7" in failing(draft(key_points=[kp(Q1), kp(overlap)]))


@pytest.mark.parametrize("sp", ["reported_view", "ironic", "unclear"])
def test_hc8_speaker(sp):
    assert "HC8" in failing(draft(key_points=[kp(Q1, sp), kp(Q2)]))


def test_hc9_surname_in_question_and_toggle():
    assert "HC9" in failing(draft(question="What is said about this?"))
    assert "HC9" not in failing(draft(question="what does LOCKE say?"))
    off = load_settings({"checks": {"require_author_in_question": False}})
    assert "HC9" not in failing(draft(question="What is said?"), settings=off)


def test_hc10_burke_quoted_opponent_but_not_other_authors():
    # a Burke-style paragraph quoting an opponent in straight quotes
    inner = " ".join(TOK[30:50])
    text = " ".join(TOK[:28]) + ' Dr. Price says, "' + inner + '" ' + " ".join(TOK[60:80]) + "."
    burke = mkpara(text, author="Edmund Burke")
    d = draft(question="What does Burke say about this matter?",
              key_points=[kp(" ".join(TOK[3:11])), kp(" ".join(text.split('"')[1].split()[2:10]))])
    assert "HC10" in failing(d, burke)
    assert "HC10" not in failing(d.model_copy(update={"question": "What does Locke say?"}), mkpara(text))
    d2 = d.model_copy(update={"question": "What does Locke say about this matter?"})
    flags = K.soft_flags(d2.question, K.run_hard_checks(d2, mkpara(text), SETTINGS).key_points, mkpara(text), SETTINGS)
    assert "quote_in_quotation_marks" in flags  # SF5 for authors without HC10


def test_sf1_leakage_and_sf2_statement_copies_quote():
    p = mkpara(TEXT)
    res = K.run_hard_checks(draft(), p, SETTINGS)
    assert "leakage" not in K.soft_flags("What does Locke say about this matter?", res.key_points, p, SETTINGS)
    leak = "Why does Locke say that " + " ".join(TOK[10:15]) + "?"
    assert "leakage" in K.soft_flags(leak, res.key_points, p, SETTINGS)
    d = draft(key_points=[kp(Q1, statement=Q1), kp(Q2)])
    res2 = K.run_hard_checks(d, p, SETTINGS)
    assert "statement_copies_quote" in K.soft_flags(d.question, res2.key_points, p, SETTINGS)


def flags_for(p):
    d = draft(question=f"What does {p.author.split()[-1]} say about this matter?")
    res = K.run_hard_checks(d, p, SETTINGS)
    assert res.ok, res.failures
    return K.soft_flags(d.question, res.key_points, p, SETTINGS)


def test_sf3_cues_names_and_bad_examples():
    f = flags_for(mkpara("It may be objected, says he, that Barclay is wrong. " + TEXT))
    assert "attribution_cue:it may be objected" in f and "attribution_cue:Barclay" in f
    # section 8.4: Locke 233 (Barclay), Hobbes ch. 42 (Bellarmine) and ch. 15 (Foole), Burke Price
    assert "attribution_cue:Barclay" in flags_for(mkpara("Sect. 233. As Barclay says it. " + TEXT))
    assert "attribution_cue:Bellarmine" in flags_for(
        mkpara("Cardinal Bellarmine bringeth his chiefe argument. " + TEXT, author="Thomas Hobbes"))
    assert "attribution_cue:Foole" in flags_for(
        mkpara("The Foole hath sayd in his heart. " + TEXT, author="Thomas Hobbes"))
    assert "attribution_cue:Price" in flags_for(
        mkpara("Dr. Price in the Revolution Society told us so. " + TEXT, author="Edmund Burke"))
    assert not [x for x in flags_for(mkpara(TEXT)) if x.startswith("attribution_cue")]


def test_sf4_rebuttal_next_mill_unmarked_objection():
    p = mkpara(TEXT, author="John Stuart Mill", context_after="I answer that it is assuming very much more.")
    assert "rebuttal_next" in flags_for(p)
    assert "rebuttal_next" not in flags_for(mkpara(TEXT, context_after="The next thing is different."))
    for m in ("To this I answer", "It is not true that", "—This is possible"):
        assert A.rebuttal_next(m + " ...")


def test_sf5_mill_first_person_inside_quotes():
    text = TEXT + ' He objects: "I do not see why this is so, and I say no."'
    assert "quote_in_quotation_marks" in flags_for(mkpara(text, author="John Stuart Mill"))
    assert "quote_in_quotation_marks" not in flags_for(mkpara(TEXT, author="John Stuart Mill"))


def test_sf6_sensitive_term_sf7_margin_note_sf9_split():
    s = load_settings({"review": {"sensitive_terms": ["labour"]}})
    p = mkpara(TEXT)
    res = K.run_hard_checks(draft(), p, s)
    assert "sensitive_term" in K.soft_flags("q", res.key_points, p, s)
    assert "sensitive_term" not in K.soft_flags("q", res.key_points, p, SETTINGS)
    fused = mkpara("Of the Law. The " + TEXT)
    assert "margin_note_prefix" in K.soft_flags("q", [], fused, SETTINGS)
    assert "margin_note_prefix" not in K.soft_flags("q", [], mkpara(TEXT.lower()), SETTINGS)
    two = mkpara(TEXT, chunks=[("a:c0", TEXT[:500]), ("a:c1", TEXT[300:])])
    assert "split_paragraph" in K.soft_flags("q", [], two, SETTINGS)
    assert "split_paragraph" not in K.soft_flags("q", [], p, SETTINGS)


# --------------------------------------------------------------------------- attribution advisory


def advisory(items):
    return ScriptedClient(lambda call, i: {"items": items})


def test_advisory_verifies_evidence_and_labels_unverified():
    p = mkpara(TEXT, context_after="Next paragraph begins with a distinctive phrase right here.")
    c = advisory([
        {"key_point_id": "kp1", "speaker": "author_sincere", "explanation": "e", "evidence": TEXT.split(".")[0]},
        {"key_point_id": "kp2", "speaker": "reported_view", "explanation": "e", "evidence": "invented words not there"},
        {"key_point_id": "kp3", "speaker": "unclear", "explanation": "e", "evidence": "distinctive phrase right here"},
    ])
    out, sha = A.run_advisory(c, p, [("kp1", "s", "q"), ("kp2", "s", "q")], SETTINGS)
    assert [a.evidence_verified for a in out] == [True, False, True]
    assert out[1].label == "unverified advice" and len(sha) == 64
    assert "CONTEXT AFTER" in c.calls[0]["user"] and "kp1: s" in c.calls[0]["user"]
