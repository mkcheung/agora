"""M1: builder/checks.py and builder/card_validation.py must agree on HC2-HC7, HC9, HC10 (and the
false-premise premise check) for the same card."""

import random

import pytest

from integrity.builder import card_validation as cv
from integrity.builder import checks
from integrity.builder.drafter import DraftCard, DraftKeyPoint, FalsePremiseDraft
from integrity.common import textnorm
from integrity.common.schema import Anchor, Card, KeyPoint
from integrity.common.settings import load_settings
from integrity.tests.builder_helpers import mkpara

BASE = (
    'Society is indeed a "contract" with many "partners and heirs of old" and “so on”. Subordinate '
    "contracts for objects of mere occasional interest may be dissolved at pleasure; but the state ought not "
    "to be considered as nothing better than a partnership agreement in a trade of pepper and coffee, calico "
    'or tobacco, or some other such low concern, to be taken up for a little temporary interest, and to be '
    'dissolved by the fancy of the parties; as Burke says, "it is a partnership in all science" and more. '
)
TEXT = BASE * 3
CHECKED = {"HC2", "HC3", "HC4", "HC5", "HC6", "HC7", "HC9", "HC10"}
QUESTIONS = ["What does Burke say?", "What does Locke say?", "Why?", "what burke?", "", "Is Burke right? Yes?"]


def _case(rng, words, author, p, settings):
    kind = rng.choice(["passage", "false_premise"])
    premise = rng.choice(["", "  ", "A premise."])
    quotes = []
    for _ in range(rng.choice([1, 2, 2, 3, 4])):
        i = rng.randrange(0, len(words) - 4)
        quotes.append(" ".join(words[i:i + rng.randrange(1, 30)]))
    if rng.random() < 0.1:
        quotes[-1] = quotes[0]
    if rng.random() < 0.05:
        quotes[0] = "not in the text at all"
    question = rng.choice(QUESTIONS)
    draft_cls = FalsePremiseDraft if kind == "false_premise" else DraftCard
    draft = draft_cls(
        status="ok", question=question, **({"premise": premise} if kind == "false_premise" else {}),
        key_points=[DraftKeyPoint(statement="s", quote=q, speaker="author_sincere") for q in quotes],
    )
    res = checks.run_hard_checks(draft, p, settings, kind)
    a = {f.check for f in res.failures} & CHECKED
    a_prem = any("premise is empty" in f.detail for f in res.failures)
    kps = []
    for j, q in enumerate(quotes, 1):
        sp = textnorm.find_span(q, TEXT)
        if sp is None:
            kps.append(KeyPoint(id=f"kp{j}", statement="s", quote=q, span=[0, 0], chunk_ids=[]))
            continue
        src = TEXT[sp[0]:sp[1]]
        kps.append(KeyPoint(id=f"kp{j}", statement="s", quote=src, span=list(sp),
                            chunk_ids=[pid for pid, ct in p.chunks if textnorm.find_span(src, ct)]))
    card = Card(
        card_id="c", type=kind, question=question, premise=premise if kind == "false_premise" else None,
        key_points=kps,
        anchor=Anchor(author=author, work="W", work_id="w", block_id="w:1", locator="L", text=TEXT,
                      chunks=[{"passage_id": pid, "text": t} for pid, t in p.chunks]),
    )
    fails = cv.validate_card(card, settings.author_rules(author))
    b = {f.check for f in fails}
    return a, b, (a_prem, any("premise is empty" in f.detail for f in fails)), quotes


@pytest.mark.parametrize("author", ["Edmund Burke", "John Locke"])
def test_card_validation_agrees_with_checks(author):
    settings = load_settings()
    cut = 700
    p = mkpara(TEXT, author=author, work="W", work_id="w", position=0, block_id="w:1",
               chunks=[("w:1:c0", TEXT[:cut]), ("w:1:c1", TEXT[cut - 200:])])
    words = TEXT.split(" ")
    rng = random.Random(11)
    n = disagreements = hc10 = premise_cases = 0
    examples = []
    for _ in range(1050):
        a_checks, b_checks, (pa, pb), quotes = _case(rng, words, author, p, settings)
        n += 1
        hc10 += "HC10" in a_checks
        premise_cases += pa
        if a_checks != b_checks or pa != pb:
            disagreements += 1
            examples.append((a_checks, b_checks, pa, pb, quotes[:2]))
    assert n >= 1050 and disagreements == 0, examples[:3]
    assert premise_cases > 0  # the premise check was exercised, not vacuous
    if settings.author_rules(author).get("quoted_text_is_other_speaker"):
        assert hc10 > 50  # HC10 actually fired in the fuzz


def test_card_validation_hc10_overlap_not_just_start():
    """A quote that STARTS before a quotation mark but runs into it fails HC10 in both modules."""
    settings = load_settings()
    p = mkpara(TEXT, author="Edmund Burke", work="W", work_id="w", position=0, block_id="w:1")
    quote = 'Society is indeed a "contract" with many'
    sp = textnorm.find_span(quote, TEXT)
    assert sp is not None
    q2 = "Subordinate contracts for objects of mere occasional interest"
    sp2 = textnorm.find_span(q2, TEXT)
    kps = [KeyPoint(id="kp1", statement="s", quote=TEXT[sp[0]:sp[1]], span=list(sp), chunk_ids=["w:1:c0"]),
           KeyPoint(id="kp2", statement="s", quote=TEXT[sp2[0]:sp2[1]], span=list(sp2), chunk_ids=["w:1:c0"])]
    card = Card(card_id="c", question="What does Burke say?", key_points=kps,
                anchor=Anchor(author="Edmund Burke", work="W", work_id="w", block_id="w:1", locator="L", text=TEXT,
                              chunks=[{"passage_id": "w:1:c0", "text": TEXT}]))
    fails = cv.validate_card(card, settings.author_rules("Edmund Burke"))
    assert any(f.check == "HC10" and f.detail.startswith("kp1") for f in fails)
    draft = DraftCard(status="ok", question="What does Burke say?", key_points=[
        DraftKeyPoint(statement="s", quote=quote, speaker="author_sincere"),
        DraftKeyPoint(statement="s", quote=q2, speaker="author_sincere")])
    assert any(f.check == "HC10" for f in checks.run_hard_checks(draft, p, settings).failures)


def test_false_premise_card_needs_premise():
    settings = load_settings()
    q = "Subordinate contracts for objects of mere occasional interest"
    q2 = "but the state ought not to be considered as nothing better"
    sps = [textnorm.find_span(x, TEXT) for x in (q, q2)]
    kps = [KeyPoint(id=f"kp{i}", statement="s", quote=TEXT[a:b], span=[a, b], chunk_ids=["w:1:c0"])
           for i, (a, b) in enumerate(sps, 1)]
    anchor = Anchor(author="John Locke", work="W", work_id="w", block_id="w:1", locator="L", text=TEXT,
                    chunks=[{"passage_id": "w:1:c0", "text": TEXT}])
    bad = Card(card_id="c", type="false_premise", question="Did Locke say X?", premise=" ", key_points=kps,
               anchor=anchor)
    good = bad.model_copy(update={"premise": "Locke said X."})
    rules = settings.author_rules("John Locke")
    assert any("premise" in f.detail for f in cv.validate_card(bad, rules))
    assert cv.validate_card(good, rules) == []
