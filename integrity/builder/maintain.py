"""Maintenance: compare every card of the latest sheet with the current corpus and re-anchor (plan 7.10).

Statuses: ok, text_changed, moved, ambiguous, missing. ``--apply`` re-anchors text_changed and moved cards
into a new sheet version; question and key-point statement wording never change, and ambiguous and
missing cards are never touched.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from integrity.builder import publish as pub
from integrity.builder.card_validation import (
    ValidateCard,
    format_failures,
    make_validator,
)
from integrity.builder.corpus import Corpus, CorpusError, Paragraph, load_corpus
from integrity.common import sheets, textnorm
from integrity.common.schema import Anchor, Card, KeyPoint, Sheet, skeleton_sha256
from integrity.common.settings import Settings

STATUSES = ("ok", "text_changed", "moved", "ambiguous", "missing")


class MaintainError(Exception):
    def __init__(self, message: str, exit_code: int = 1):
        super().__init__(message)
        self.exit_code = exit_code


@dataclass
class CardCheck:
    card_id: str
    status: str
    detail: str = ""
    target: Paragraph | None = None  # re-anchor target for text_changed / moved
    candidates: list[str] = field(default_factory=list)  # block ids for ambiguous


def _has_all_quotes(card: Card, text: str) -> bool:
    return all(textnorm.find_span(kp.quote, text) is not None for kp in card.key_points)


def check_card(card: Card, corpus: Corpus, by_block: dict[str, Paragraph] | None = None) -> CardCheck:
    by_block = by_block if by_block is not None else corpus.by_block_id()
    a = card.anchor
    p = by_block.get(a.block_id)
    if p is not None and skeleton_sha256(p.text) == a.skeleton_sha256:
        return CardCheck(card.card_id, "ok")
    if p is not None and _has_all_quotes(card, p.text):
        return CardCheck(card.card_id, "text_changed", "paragraph text changed; quotes still present", target=p)
    found = [q for q in corpus.paragraphs if q.work_id == a.work_id and _has_all_quotes(card, q.text)]
    why = "block_id not in the corpus" if p is None else "block_id now points at text without the quotes"
    if len(found) == 1:
        return CardCheck(card.card_id, "moved", f"{why}; found in {found[0].block_id}", target=found[0])
    if len(found) > 1:
        return CardCheck(card.card_id, "ambiguous", f"{why}; {len(found)} paragraphs contain every quote",
                         candidates=[q.block_id for q in found])
    return CardCheck(card.card_id, "missing", f"{why}; no paragraph contains every quote")


def check_sheet(sheet: Sheet, corpus: Corpus) -> list[CardCheck]:
    by_block = corpus.by_block_id()
    return [check_card(c, corpus, by_block) for c in sheet.cards]


_INT_ANCHOR_FIELDS = ("chapter", "section", "paragraph", "position")


def anchor_kwargs(p: Paragraph) -> dict:
    """Paragraph.anchor_fields() for schema.Anchor. ``part``, ``book`` and ``volume`` are text labels
    (for example Locke's ``book = "Book II"``) and are kept as they are; only the genuinely numeric fields
    (chapter, section, paragraph, position) are dropped when they hold something that is not an integer."""
    out = p.anchor_fields()
    for k in _INT_ANCHOR_FIELDS:
        if k in out and out[k] is not None and (isinstance(out[k], bool) or not isinstance(out[k], int)):
            del out[k]
    return out


def reanchor_card(card: Card, p: Paragraph) -> Card:
    """The card re-anchored to paragraph ``p``: anchor and key-point spans/quotes/chunk ids are recomputed;
    question, key-point statements, flags, provenance and review are untouched."""
    anchor = Anchor(**anchor_kwargs(p), skeleton_sha256=skeleton_sha256(p.text))
    kps: list[KeyPoint] = []
    for kp in card.key_points:
        found = textnorm.find_span(kp.quote, p.text)
        if found is None:
            raise MaintainError(f"{kp.id}: quote not found in {p.block_id}")
        s, e = found
        quote = p.text[s:e]
        chunk_ids = [pid for pid, t in p.chunks if textnorm.find_span(quote, t) is not None]
        kps.append(kp.model_copy(update={"quote": quote, "span": [s, e], "chunk_ids": chunk_ids}))
    return card.model_copy(deep=True, update={"anchor": anchor, "key_points": kps})


@dataclass
class CheckReport:
    sheet: Sheet
    corpus: Corpus
    results: list[CardCheck]

    def counts(self) -> dict[str, int]:
        return {s: sum(1 for r in self.results if r.status == s) for s in STATUSES}


def run_check(settings: Settings, corpus: Corpus | None = None) -> CheckReport:
    try:
        sheet = sheets.load_sheet(settings.data_dir, "latest")
    except sheets.SheetError as e:
        raise MaintainError(f"no valid published answer sheet: {e}", e.exit_code) from e
    if corpus is None:
        try:
            corpus = load_corpus(settings)
        except CorpusError as e:
            raise MaintainError(f"corpus problem: {e}", e.exit_code) from e
    return CheckReport(sheet, corpus, check_sheet(sheet, corpus))


def format_report(rep: CheckReport) -> str:
    lines = [f"sheet {rep.sheet.version}: {len(rep.results)} cards checked against corpus {rep.corpus.corpus_version}"]
    for s, n in rep.counts().items():
        lines.append(f"  {s:<13}{n}")
    for r in rep.results:
        if r.status == "ok":
            continue
        lines.append(f"{r.status.upper():<13}{r.card_id}  {r.detail}")
        for b in r.candidates:
            lines.append(f"               candidate: {b}")
        if r.status == "missing":
            lines.append(f"               suggested: python -m integrity retire {r.card_id} --reason \"source paragraph missing\"")
    return "\n".join(lines)


@dataclass
class ApplyResult:
    reanchored: list[str]
    failed: list[tuple[str, str]]
    version: str | None


def apply_reanchoring(
    settings: Settings, rep: CheckReport, validate_card: ValidateCard | None = None
) -> ApplyResult:
    """Re-anchor text_changed and moved cards, run the hard checks on each, publish a new version."""
    validate = validate_card or make_validator(settings)
    by_id = {c.card_id: c for c in rep.sheet.cards}
    replacements: list[Card] = []
    failed: list[tuple[str, str]] = []
    for r in rep.results:
        if r.status not in ("text_changed", "moved") or r.target is None:
            continue
        try:
            new = reanchor_card(by_id[r.card_id], r.target)
        except MaintainError as e:
            failed.append((r.card_id, str(e)))
            continue
        fails = validate(new)
        if fails:
            failed.append((r.card_id, format_failures(fails)))
            continue
        replacements.append(new)
    if not replacements:
        return ApplyResult([], failed, None)
    try:
        res = pub.publish_with_replacements(
            settings, replacements, note=f"re-anchored {len(replacements)} cards", validate_card=validate
        )
    except pub.PublishError as e:
        raise MaintainError(str(e), e.exit_code) from e
    return ApplyResult([c.card_id for c in replacements], failed, res.version)
