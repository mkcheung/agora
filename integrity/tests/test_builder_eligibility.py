"""Eligibility filters EL-* with fixtures for each section 8.1 hazard and the section 8.4 bad examples."""

import json

from integrity.builder import eligibility as E
from integrity.common.settings import load_settings
from integrity.tests.builder_helpers import mkpara, prose


def reasons(paras, settings=None, used=None):
    s = settings or load_settings()
    return {v.paragraph.block_id: v.reasons for v in E.evaluate(paras, s, used)}


def one(text, **kw):
    p = mkpara(text, **kw)
    return reasons([p])[p.block_id]


GOOD = prose(1)


def test_good_paragraph_is_eligible():
    assert one(GOOD) == []


def test_el_type_notes_verse_table():
    assert "EL-type" in one(GOOD, content_type="note")
    assert "EL-type" in one(GOOD, content_type="verse")


def test_el_len_with_author_override_for_mill():
    mid = prose(2, 10)  # between 600 and 800 chars
    assert 600 <= len(mid) < 800
    assert one(mid) == []
    assert "EL-len" in one(mid, author="John Stuart Mill")
    assert "EL-len" in one("Short.")
    assert "EL-len" in one(GOOD * 8)


def test_el_rebuild():
    p = mkpara(GOOD)
    p.rebuild_uncertain = True
    assert "EL-rebuild" in reasons([p])[p.block_id]


def test_el_lang_latin_and_non_english():
    latin = "Quid ergo, nulline casus incidere possunt quod est et enim atque vel nec esse regem populo. " * 8
    assert "EL-lang" in one(latin)
    assert "EL-lang" in one("Zzz qqq xxx yyy. " * 60)


def test_el_quote_led_and_ibid_hooker_notes():
    assert "EL-quote-led" in one("(*" + GOOD)
    assert "EL-quote-led" in one("(**" + GOOD)
    assert "EL-quote-led" in one("“" + GOOD)
    assert "EL-quote-led" in one('"' + GOOD)
    assert "EL-ibid" in one(GOOD[:-1] + ", Ibid.)")


def test_el_quoted_fraction_and_hobbes_override():
    third = prose(3, 3)
    text = prose(4, 7) + ' "' + prose(5, 5) + '" ' + prose(6, 1)
    frac = E.quoted_fraction(text)
    assert 0.3 < frac < 0.5, frac
    assert "EL-quoted" in one(text)
    assert "EL-quoted" not in one(text, author="Thomas Hobbes")
    assert third
    # an unclosed opening quote counts to the end of the paragraph
    assert E.quoted_fraction("abc " + '"' + "x" * 96) > 0.95


def test_el_introducer_barclay_and_hooker_typed_as_prose():
    for lead in ("His words are,", "where he says,", "tells them thus,", "these words:", "a little after,",
                 "In English thus:", "which in English runs thus:"):
        before = mkpara(prose(7, 3) + " " + lead, position=0)
        after = mkpara(GOOD, position=1)
        assert "EL-introducer" in reasons([before, after])[after.block_id], lead
    ok = mkpara(prose(7, 3) + " I answer,", position=0)
    assert "EL-introducer" not in reasons([ok, mkpara(GOOD, position=1)])[mkpara(GOOD, position=1).block_id]


def test_el_gap_midsentence_questions_money_bible_editorial():
    assert "EL-gap" in one(GOOD + " [Greek: logos]")
    assert "EL-midsentence" in one(GOOD[:-1] + ", Therefore,")
    q = " ".join(f"Is it true that point {i} holds?" for i in range(24))
    assert "EL-questions" in one(q + " " + GOOD)
    money = " 10 l. a year, 5 lacs, 3 pagodas, 4 per cent."
    assert "EL-money" in one(GOOD + money)
    bible = " (Matt. 5, Luke 4, John 3.)"
    assert "EL-bible" not in one(GOOD + " (Matt. 5.)")
    assert "EL-bible" in one(GOOD + " (Gen. 1.) (Exod. 2.) (Matt. 5.) (Luke 4.)")
    assert bible
    assert "EL-editorial" in one("N.B. " + GOOD)
    assert "EL-editorial" in one(GOOD + " So says the editor.")
    assert "EL-editorial" in one("Mr. Fox then rose. " + GOOD)


def test_el_deny_and_locke_barclay_paragraph():
    s = load_settings()
    p = mkpara(GOOD, work_id="pg7370:main", locator="Book II, Chapter 19, §233, paragraph 30 (edition-specific)")
    assert "EL-deny" in reasons([p], s)[p.block_id]
    p2 = mkpara(GOOD, work_id="pg7370:main", locator="Book II, Chapter 19, §239, paragraph 44 (edition-specific)")
    assert "EL-deny" not in reasons([p2], s)[p2.block_id]
    # the same locator in another work is not denied
    p3 = mkpara(GOOD, work_id="pgX:main", locator="Book II, Chapter 19, §233, paragraph 30 (edition-specific)")
    assert "EL-deny" not in reasons([p3], s)[p3.block_id]


def test_bad_example_bellarmine_is_denied_and_foole_is_flagged():
    from integrity.builder.attribution import cue_phrases

    s = load_settings()
    bell = mkpara(GOOD, author="Thomas Hobbes", work_id="pg3207:main",
                  locator="Part III, Chapter 42, The First Book, paragraph 81 (edition-specific)")
    assert "EL-deny" in reasons([bell], s)[bell.block_id]
    foole = "The Foole hath sayd in his heart, there is no such thing as Justice. " + GOOD
    assert "Foole" in cue_phrases(foole, "Thomas Hobbes")


def test_bad_example_burke_price_quote_led_is_excluded():
    price = '"What an eventful period is this! I am thankful that I have lived to it; ' + GOOD + '"'
    r = one(price, author="Edmund Burke")
    assert "EL-quote-led" in r and "EL-quoted" in r


def test_bad_example_mill_unmarked_objection_is_flagged_not_excluded():
    from integrity.builder.attribution import rebuttal_next

    objection = mkpara(
        "The objection likely to be made to this argument would take some such form as the following. " + GOOD,
        author="John Stuart Mill", work_id="w3:main", position=0,
        context_after="I answer that it is assuming very much more.",
    )
    assert reasons([objection])[objection.block_id] == []  # code cannot tell; the flags do
    assert rebuttal_next(objection.context_after)


def test_el_used_from_sheets_drafts_and_neighbours(data_dir):
    from integrity.common import sheets
    from integrity.common.schema import skeleton_sha256
    from integrity.tests.helpers import make_card, make_sheet_dict

    paras = [mkpara(prose(10 + i), position=i, block_id=f"w1:main:b{i}") for i in range(6)]
    s = load_settings()
    assert all(not r for r in reasons(paras, s, E.collect_used(data_dir)).values())
    card = make_card()
    card["anchor"]["block_id"] = "w1:main:b1"
    card["anchor"]["skeleton_sha256"] = "zz"
    card["card_id"] = "c-1"
    sheets.write_sheet(data_dir, make_sheet_dict(cards=[card]))
    r = reasons(paras, s, E.collect_used(data_dir))
    assert [i for i in range(6) if "EL-used" in r[f"w1:main:b{i}"]] == [0, 1, 2]  # +-1 neighbours
    # a pending draft excludes by skeleton hash even when the block id changed
    d = data_dir / "drafts" / "b-1"
    d.mkdir(parents=True)
    row = {"anchor": {"block_id": "other", "skeleton_sha256": skeleton_sha256(paras[5].text)},
           "review": {"status": "pending"}}
    (d / "cards.jsonl").write_text(json.dumps(row) + "\n")
    rej = d.parent / "b-2"
    rej.mkdir()
    (rej / "cards.jsonl").write_text(json.dumps({"anchor": {"block_id": "w1:main:b3"},
                                                 "review": {"status": "rejected"}}) + "\n")
    r = reasons(paras, s, E.collect_used(data_dir))
    assert "EL-used" in r["w1:main:b5"] and "EL-used" in r["w1:main:b4"]
    assert "EL-used" not in r["w1:main:b3"]  # rejected drafts do not count


def test_all_reasons_recorded_not_only_the_first():
    p = mkpara("(*short", content_type="note")
    assert {"EL-type", "EL-len", "EL-quote-led"} <= set(reasons([p])[p.block_id])


def test_normalize_reason():
    assert E.normalize_reason("len") == "EL-len" and E.normalize_reason("el-quote-led") == "EL-quote-led"
