"""Card-only re-validation (hard checks that need nothing but the stored card and common/textnorm).

Used by review (after an edit) and publish (every card). Covers HC2, HC3, HC4, HC5, HC6, HC7, HC9,
HC10 and (only when a QuoteIndex is passed, i.e. never at review/publish) HC11. HC1 (draft status) and HC8 (drafter speaker label) are not stored on a Card and cannot be
re-checked here. Parity with builder/checks.py on these checks is enforced by test_builder_review_parity (quoted ranges come from eligibility.quoted_ranges).
"""

from __future__ import annotations

import re
from collections.abc import Callable

from integrity.builder.corpus import QuoteIndex
from integrity.builder.eligibility import quoted_ranges
from integrity.common import textnorm
from integrity.common.schema import Card, CheckFailure
from integrity.common.settings import Settings

ValidateCard = Callable[[Card], list[CheckFailure]]


def uniqueness_failures(card: Card, corpus: QuoteIndex) -> list[CheckFailure]:
    """HC11: every key-point quote must occur in exactly one paragraph of the card's work."""
    return [
        CheckFailure(check="HC11", detail=f"{kp.id}: quote does not occur in exactly one paragraph of the work")
        for kp in card.key_points
        if corpus.count(card.anchor.work_id, kp.quote) != 1
    ]


def validate_card(card: Card, rules: dict, corpus: QuoteIndex | None = None) -> list[CheckFailure]:
    """Run the card-only hard checks with already-resolved per-author rules."""
    fails: list[CheckFailure] = []

    def fail(check: str, detail: str) -> None:
        fails.append(CheckFailure(check=check, detail=detail))

    text = card.anchor.text
    q = card.question.strip()
    # HC2
    if not q:
        fail("HC2", "question is empty")
    else:
        if not q.endswith("?"):
            fail("HC2", "question does not end with '?'")
        if len(q) > rules["max_question_chars"]:
            fail("HC2", f"question is {len(q)} characters (max {rules['max_question_chars']})")
    if card.type == "false_premise" and not (getattr(card, "premise", "") or "").strip():
        fail("HC2", "premise is empty")
    # HC3
    n = len(card.key_points)
    if n < 2 or n > 3:
        fail("HC3", f"{n} key points (need 2 or 3)")
    elif n == 3 and len(text) < rules["three_points_min_chars"]:
        fail("HC3", f"3 key points but the paragraph has {len(text)} characters (< {rules['three_points_min_chars']})")
    ids = [kp.id for kp in card.key_points]
    if len(set(ids)) != len(ids):
        fail("HC2", "duplicate key point ids")
    chunk_text = {c.passage_id: c.text for c in card.anchor.chunks}
    spans: list[tuple[str, int, int]] = []
    for kp in card.key_points:
        if not kp.statement.strip():
            fail("HC2", f"{kp.id}: statement is empty")
        found = textnorm.find_span(kp.quote, text)
        if found is None:
            fail("HC4", f"{kp.id}: quote not found in the paragraph")
            continue
        s, e = found
        # the stored span and quote must be the source text at a valid match
        sp = kp.span
        if len(sp) != 2 or not (0 <= sp[0] < sp[1] <= len(text)) or text[sp[0]:sp[1]] != kp.quote \
                or textnorm.find_span(text[sp[0]:sp[1]], text) is None:
            fail("HC4", f"{kp.id}: span {sp} does not match the quote in the paragraph")
        else:
            s, e = sp[0], sp[1]
        # HC5
        wc = textnorm.word_count(kp.quote)
        if textnorm.has_ellipsis(kp.quote):
            fail("HC5", f"{kp.id}: quote contains an ellipsis")
        if not rules["quote_min_words"] <= wc <= rules["quote_max_words"]:
            fail("HC5", f"{kp.id}: quote is {wc} words (need {rules['quote_min_words']}-{rules['quote_max_words']})")
        # HC6
        if not kp.chunk_ids:
            fail("HC6", f"{kp.id}: no chunk_ids")
        for cid in kp.chunk_ids:
            if cid not in chunk_text:
                fail("HC6", f"{kp.id}: chunk {cid} is not one of the anchor chunks")
            elif textnorm.find_span(kp.quote, chunk_text[cid]) is None:
                fail("HC6", f"{kp.id}: quote is not wholly inside chunk {cid}")
        spans.append((kp.id, s, e))
        # HC10
        if rules.get("quoted_text_is_other_speaker"):
            for a, b in quoted_ranges(text):
                if s < b and a < e:  # same rule as checks.py: any overlap with a quoted range fails
                    fail("HC10", f"{kp.id}: quote lies inside quotation marks (author's quoted text is another speaker)")
                    break
    # HC7
    for i, (ia, sa, ea) in enumerate(spans):
        for ib, sb, eb in spans[i + 1:]:
            if sa < eb and sb < ea:
                fail("HC7", f"{ia} and {ib}: quote spans overlap or coincide")
    quotes = [textnorm.skeleton(kp.quote) for kp in card.key_points]
    if len(set(quotes)) != len(quotes):
        fail("HC7", "two key points have the same quote")
    # HC9
    if rules.get("require_author_in_question") and q:  # an empty question is already an HC2 failure (as in checks.py)
        parts = card.anchor.author.split()
        surname = parts[-1] if parts else ""
        if surname and not re.search(rf"(?<!\w){re.escape(surname)}(?!\w)", q, re.IGNORECASE):
            fail("HC9", f"question does not contain the author's surname ({surname})")
    if corpus is not None:
        fails.extend(uniqueness_failures(card, corpus))
    return fails


def make_validator(settings: Settings, corpus: QuoteIndex | None = None) -> ValidateCard:
    """Default ``validate_card`` seam: card-only hard checks with the per-author rules from settings."""

    def _validate(card: Card) -> list[CheckFailure]:
        return validate_card(card, settings.author_rules(card.anchor.author), corpus)

    return _validate


def format_failures(fails: list[CheckFailure]) -> str:
    return "\n".join(f"  {f.check}: {f.detail}" for f in fails)
