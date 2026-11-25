"""Integration tests on the real corpus (skipped when the EPUBs are absent). Tests may import the
main program's modules; module code may not."""

import re
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(not any(ROOT.glob("*.epub")), reason="EPUBs not present")


@pytest.fixture(scope="module")
def real():
    from integrity.builder import eligibility as E
    from integrity.builder.corpus import load_corpus
    from integrity.common.settings import load_settings

    s = load_settings()
    c = load_corpus(s)
    return s, c, E.evaluate(c.paragraphs, s)


def test_rebuild_equals_parser_block_text_for_every_paragraph(real):
    import ingest
    from parsers import parse_epub

    _s, corpus, _v = real
    parsed = {}
    for w in ingest.WORKS:
        for d in parse_epub(ROOT / w["file"], w["profile"], {"file": w["file"]}):
            parsed[d.metadata["block_id"]] = (d.page_content, d.metadata["content_type"])
    assert len(parsed) == len(corpus.paragraphs)
    multi = [p for p in corpus.paragraphs if len(p.chunks) > 1]
    assert len(multi) > 300
    bad = [p.block_id for p in corpus.paragraphs if parsed[p.block_id][1] != "table" and p.text != parsed[p.block_id][0]]
    assert bad == [] and not [p for p in corpus.paragraphs if p.content_type != "table" and p.rebuild_uncertain]


def test_counts_and_every_stratum_matches_something_real(real, capsys):
    from integrity.builder import strata as ST

    s, corpus, verdicts = real
    assert len(corpus.paragraphs) == 7900
    rules = ST.author_strata(s, corpus.paragraphs)
    el = Counter()
    for v in verdicts:
        n = ST.assign(v.paragraph, rules[v.paragraph.author])
        if n and v.eligible:
            el[n] += 1
    names = [r.name for rs in rules.values() for r in rs]
    assert all(el[n] > 0 for n in names), {n: el[n] for n in names}
    per_author = Counter(v.paragraph.author for v in verdicts if v.eligible)
    with capsys.disabled():
        print("\neligible per author:", dict(per_author))


def test_each_denylist_entry_hits_real_paragraphs(real):
    s, _c, verdicts = real
    hits = {}
    for i, e in enumerate(s.eligibility.denylist):
        hits[i] = [v.paragraph.locator for v in verdicts
                   if v.paragraph.work_id == (e.work_id or v.paragraph.work_id) and re.search(e.locator_regex, v.paragraph.locator)]
    assert hits and all(hits[i] for i in hits), hits
    assert len(hits[0]) == 4  # section 233, 237 (two paragraphs) and 238


def test_known_good_and_bad_paragraphs(real):
    _s, _c, verdicts = real
    by_loc = {(v.paragraph.work_id, v.paragraph.locator.split(" (")[0]): v for v in verdicts}
    ok = by_loc.get(("pg7370:main", "Book II, Chapter 5, §27, paragraph 3"))
    if ok is not None:
        assert ok.eligible
    barclay = by_loc[("pg7370:main", "Book II, Chapter 19, §233, paragraph 30")]
    assert "EL-deny" in barclay.reasons and "EL-introducer" in barclay.reasons
    hooker = by_loc[("pg7370:main", "Book II, Chapter 2, §5, paragraph 4")]
    assert "EL-introducer" in hooker.reasons
    price = next(v for v in verdicts if v.paragraph.work_id == "pg15679:reflections" and v.paragraph.paragraph == 116)
    assert "EL-quote-led" in price.reasons


def test_fixed_seed_dry_run_is_reproducible_on_the_real_corpus(real):
    from integrity.builder import sampler

    s, corpus, verdicts = real
    from integrity.builder import eligibility as E

    el = E.eligible_paragraphs(verdicts)
    a = sampler.plan_slots(el, s, count=24, seed=7)
    b = sampler.plan_slots(el, s, count=24, seed=7)
    assert [(x.slot, x.planned.block_id) for x in a] == [(x.slot, x.planned.block_id) for x in b]
    assert len(a) == 24 and {x.author for x in a} == set(corpus.authors())


def test_real_bad_examples_are_flagged_or_excluded(real):
    from integrity.builder.attribution import cue_phrases, rebuttal_next

    _s, _c, verdicts = real
    mill = next(v for v in verdicts if v.paragraph.work_id == "pg34901:main"
                and v.paragraph.locator.startswith("Chapter 2, paragraph 5 "))
    assert mill.eligible and len(mill.paragraph.chunks) == 2  # the unmarked objection cannot be excluded by code
    assert rebuttal_next(mill.paragraph.context_after)  # ...but SF4 fires
    bell = [v for v in verdicts if v.paragraph.work_id == "pg3207:main" and "Bellarmine" in v.paragraph.text
            and "Chapter 42" in v.paragraph.locator]
    assert bell
    assert any(v.eligible for v in bell)
    for v in bell:  # every eligible Bellarmine paragraph carries the name cue
        if v.eligible:
            assert any("Bellarmine" in c for c in cue_phrases(v.paragraph.text, "Thomas Hobbes"))
    foole = next(v for v in verdicts if v.paragraph.work_id == "pg3207:main" and "The Foole hath sayd" in v.paragraph.text)
    assert "Foole" in cue_phrases(foole.paragraph.text, "Thomas Hobbes")
