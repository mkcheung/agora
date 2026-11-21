"""Hard checks HC1-HC11 (discard) and soft flags SF1-SF10 (plan section 7.6).

HC11 (added after validation): every key-point quote must occur in exactly ONE paragraph of the corpus
within its work_id (quiz matching is by text containment, so a quote that also occurs elsewhere could
produce a false "Found"). It needs the corpus, so it runs at build time only (QuoteIndex, built once per
build); review-edit and publish re-validate from the stored anchor and rely on the build-time check.

SF10 duplicate_question: the question (textnorm.skeleton) equals another card's question in the same
batch or in a published sheet. Soft flag only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from integrity.builder.attribution import (
    cue_phrases,
    first_person_in_quotes,
    rebuttal_next,
)
from integrity.builder.corpus import Paragraph, QuoteIndex
from integrity.builder.drafter import DraftCard
from integrity.builder.eligibility import quoted_ranges
from integrity.common import textnorm
from integrity.common.schema import CheckFailure, KeyPoint
from integrity.common.settings import Settings

MARGIN_WORDS = {"Of", "The", "And", "Is", "To", "In", "By"}


@dataclass
class HardResult:
    failures: list[CheckFailure] = field(default_factory=list)
    key_points: list[KeyPoint] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def surname(author: str) -> str:
    return author.split()[-1] if author.split() else author


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def surname_in(question: str, author: str) -> bool:
    """Whole-word, case-insensitive match of the author's surname (HC9)."""
    sn = surname(author)
    return bool(sn) and re.search(rf"(?<!\w){re.escape(sn)}(?!\w)", question, re.IGNORECASE) is not None


def run_hard_checks(
    draft: DraftCard, p: Paragraph, settings: Settings, kind: str = "passage",
    index: QuoteIndex | None = None,
) -> HardResult:
    """HC1-HC11 (HC11 only when a QuoteIndex is given). All applicable failures are collected (HC1 short-circuits). On success `key_points`
    holds KeyPoint objects with the source-text quote, quote_model, span and chunk_ids filled in."""
    res = HardResult()
    rules = settings.author_rules(p.author)

    def fail(check: str, detail: str) -> None:
        res.failures.append(CheckFailure(check=check, detail=detail))

    if draft.status != "ok":
        fail("HC1", f"unsuitable:{draft.unsuitable_reason or 'no reason given'}")
        return res

    q = draft.question.strip()
    if not q:
        fail("HC2", "question is empty")
    else:
        if not q.endswith("?"):
            fail("HC2", "question does not end with '?'")
        if len(q) > rules["max_question_chars"]:
            fail("HC2", f"question is {len(q)} characters (max {rules['max_question_chars']})")
    if kind == "false_premise" and not (getattr(draft, "premise", "") or "").strip():
        fail("HC2", "premise is empty")
    for i, kp in enumerate(draft.key_points, start=1):
        if not kp.statement.strip() or not kp.quote.strip():
            fail("HC2", f"key point {i} has an empty statement or quote")

    n = len(draft.key_points)
    if n < 2 or n > 3:
        fail("HC3", f"{n} key points (need 2 or 3)")
    elif n == 3 and len(p.text) < rules["three_points_min_chars"]:
        fail("HC3", f"3 key points but the paragraph has only {len(p.text)} characters (< {rules['three_points_min_chars']})")

    spans: list[tuple[int, int] | None] = []
    built: list[KeyPoint] = []
    for i, kp in enumerate(draft.key_points, start=1):
        kid = f"kp{i}"
        span = textnorm.find_span(kp.quote, p.text) if kp.quote.strip() else None
        spans.append(span)
        if span is None:
            fail("HC4", f"{kid}: quote not found in the paragraph: {kp.quote!r}")
            continue
        src = p.text[span[0]:span[1]]
        wc = textnorm.word_count(src)
        if not (rules["quote_min_words"] <= wc <= rules["quote_max_words"]) or textnorm.has_ellipsis(kp.quote):
            fail("HC5", f"{kid}: quote has {wc} words (allowed {rules['quote_min_words']}-{rules['quote_max_words']})"
                 + ("; contains an ellipsis" if textnorm.has_ellipsis(kp.quote) else ""))
        if index is not None and index.count(p.work_id, src) != 1:
            fail("HC11", f"{kid}: quote does not occur in exactly one paragraph of the work "
                 f"({index.count(p.work_id, src)} matches): {src!r}")
        chunk_ids = [pid for pid, ct in p.chunks if textnorm.find_span(src, ct) is not None]
        if not chunk_ids:
            fail("HC6", f"{kid}: quote does not lie within any single chunk")
        built.append(
            KeyPoint(id=kid, statement=kp.statement.strip(), quote=src, quote_model=kp.quote,
                     span=[span[0], span[1]], chunk_ids=chunk_ids)
        )

    found = [s for s in spans if s is not None]
    for a in range(len(found)):
        for b in range(a + 1, len(found)):
            if found[a] == found[b] or _overlaps(found[a], found[b]):
                fail("HC7", f"quote spans {found[a]} and {found[b]} are not distinct")

    for i, kp in enumerate(draft.key_points, start=1):
        if kp.speaker != "author_sincere":
            fail("HC8", f"kp{i}: speaker is {kp.speaker}")

    if rules["require_author_in_question"] and q and not surname_in(q, p.author):
        fail("HC9", f"question does not contain the author's surname ({surname(p.author)})")

    if rules.get("quoted_text_is_other_speaker"):
        qr = quoted_ranges(p.text)
        for i, s in enumerate(spans, start=1):
            if s is not None and any(_overlaps(s, r) for r in qr):
                fail("HC10", f"kp{i}: quote lies inside quotation marks (other speaker)")

    if res.ok:
        res.key_points = built
    return res


# --------------------------------------------------------------------------- soft flags


def _tokens(text: str) -> list[str]:
    return [t for t in (textnorm.skeleton(w) for w in re.findall(r"[^\W_]+", text)) if t]


def shared_ngram(a: str, b: str, n: int) -> bool:
    ta, tb = _tokens(a), _tokens(b)
    if len(ta) < n or len(tb) < n:
        return False
    grams = {tuple(tb[i:i + n]) for i in range(len(tb) - n + 1)}
    return any(tuple(ta[i:i + n]) in grams for i in range(len(ta) - n + 1))


def soft_flags(
    question: str, key_points: list[KeyPoint], p: Paragraph, settings: Settings,
    seen_questions: set[str] | None = None,
) -> list[str]:
    """SF1-SF7, SF9 and SF10 (SF8 comes from the attribution advisory and is added by the build).
    ``seen_questions`` holds the skeletons of questions already in the batch or published sheets."""
    rules = settings.author_rules(p.author)
    flags: list[str] = []
    if shared_ngram(question, p.text, rules["leakage_ngram"]):
        flags.append("leakage")
    for kp in key_points:
        st, qt = set(_tokens(kp.statement)), set(_tokens(kp.quote))
        if st and len(st & qt) / len(st) > 0.8:
            flags.append("statement_copies_quote")
            break
    for phrase in cue_phrases(p.text, p.author):
        flags.append(f"attribution_cue:{phrase}")
    if rebuttal_next(p.context_after):
        flags.append("rebuttal_next")
    qr = quoted_ranges(p.text)
    if not rules.get("quoted_text_is_other_speaker"):
        inside = any(
            any(r[0] <= kp.span[0] and kp.span[1] <= r[1] for r in qr) for kp in key_points
        )
        if inside or (p.author == "John Stuart Mill" and first_person_in_quotes(p.text)):
            flags.append("quote_in_quotation_marks")
    low = p.text.lower()
    if any(t.lower() in low for t in settings.review.sensitive_terms):
        flags.append("sensitive_term")
    first = p.text.split()[:14]
    if sum(1 for w in first if w in MARGIN_WORDS) >= 2:
        flags.append("margin_note_prefix")
    if len(p.chunks) > 1:
        flags.append("split_paragraph")
    if seen_questions is not None and textnorm.skeleton(question) in seen_questions:
        flags.append("duplicate_question")
    return flags
