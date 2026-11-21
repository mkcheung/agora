"""Interactive review of a batch's pending drafts (plan section 7.8). All I/O is injectable."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from integrity.builder.card_validation import (
    ValidateCard,
    format_failures,
    make_validator,
    uniqueness_failures,
)
from integrity.builder.corpus import Corpus, QuoteIndex, load_corpus
from integrity.common import storage, textnorm
from integrity.common.schema import Card, KeyPoint, dump
from integrity.common.settings import Settings

CHECKLIST = [
    "Can the question be answered from this paragraph alone?",
    "Does each key point say what the paragraph says, and nothing more?",
    "Is it the author speaking, not someone they quote, rebut or mock?",
    "Would a curious reader plausibly ask this?",
    "Does the question avoid copying the paragraph's distinctive wording?",
]
REJECT_REASONS = [
    "unfair question", "wrong key point", "wrong attribution", "too easy", "poor passage",
]
MENU = "[a]pprove  [e]dit  [r]eject  [s]kip  [?] checklist  [q]uit"


class ReviewError(Exception):
    exit_code = 1


class NoPendingBatch(ReviewError):
    pass


class ReviewLocked(ReviewError):
    pass


@dataclass
class ReviewResult:
    batch_id: str
    approved: int = 0
    rejected: int = 0
    skipped: int = 0
    pending: int = 0
    quit: bool = False
    actions: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- batch files


def cards_path(data_dir: Path, batch_id: str) -> Path:
    return storage.batch_dir(data_dir, batch_id) / "cards.jsonl"


def load_batch_cards(data_dir: Path, batch_id: str) -> list[Card]:
    try:
        return [Card.model_validate(r) for r in storage.read_jsonl(cards_path(data_dir, batch_id))]
    except (ValueError, OSError, TypeError) as e:  # JSONDecodeError and pydantic ValidationError are ValueErrors
        first = str(e).splitlines()[0] if str(e) else type(e).__name__
        raise ReviewError(f"batch {batch_id} has a corrupt cards.jsonl ({first})") from e


def save_batch_cards(data_dir: Path, batch_id: str, cards: list[Card]) -> None:
    storage.write_jsonl_atomic(cards_path(data_dir, batch_id), [dump(c) for c in cards])


def list_batches(data_dir: Path) -> list[str]:
    """Batch ids (directories holding cards.jsonl), newest first (ids sort chronologically)."""
    d = Path(data_dir) / "drafts"
    if not d.is_dir():
        return []
    return sorted((p.name for p in d.iterdir() if (p / "cards.jsonl").is_file()), reverse=True)


def pick_batch(data_dir: Path, batch_id: str | None) -> str:
    if batch_id:
        try:
            storage.check_batch_id(batch_id)
        except ValueError as e:
            raise ReviewError(str(e)) from e
        if not cards_path(data_dir, batch_id).is_file():
            raise NoPendingBatch(f"no such batch: {batch_id}")
        if not any(c.review.status == "pending" for c in load_batch_cards(data_dir, batch_id)):
            raise NoPendingBatch(f"batch {batch_id} has no pending cards")
        return batch_id
    for b in list_batches(data_dir):
        if any(c.review.status == "pending" for c in load_batch_cards(data_dir, b)):
            return b
    raise NoPendingBatch("no pending batch: nothing to review")


# --------------------------------------------------------------------------- rendering


class Style:
    def __init__(self, color: bool):
        self.color = color

    def bold(self, s: str) -> str:
        return f"\x1b[1m{s}\x1b[0m" if self.color else f"⟦{s}⟧"

    def dim(self, s: str) -> str:
        return f"\x1b[2m{s}\x1b[0m" if self.color else s


def highlight(text: str, spans: list[tuple[int, int]], style: Style) -> str:
    out, pos = [], 0
    for s, e in sorted(spans):
        if s < pos or e > len(text) or s >= e:
            continue
        out.append(text[pos:s])
        out.append(style.bold(text[s:e]))
        pos = e
    out.append(text[pos:])
    return "".join(out)


def _quote_ok(card: Card, kp: KeyPoint) -> bool:
    s = kp.span
    return len(s) == 2 and 0 <= s[0] < s[1] <= len(card.anchor.text) and card.anchor.text[s[0]:s[1]] == kp.quote \
        and textnorm.find_span(kp.quote, card.anchor.text) is not None


def render_card(card: Card, index: int, total: int, style: Style) -> str:
    a = card.anchor
    spans = [(kp.span[0], kp.span[1]) for kp in card.key_points if _quote_ok(card, kp)]
    lines = [
        f"[{index}/{total}]  {a.author} · {a.work} · {a.locator}   ({card.card_id}, {card.type})",
        f"FLAGS                 {', '.join(card.flags) or '-'}",
        f"CONTEXT BEFORE        {style.dim(a.context_before or '-')}",
        f"PASSAGE               {highlight(a.text, spans, style)}",
        f"CONTEXT AFTER         {style.dim(a.context_after or '-')}",
    ]
    if card.premise:
        lines.append(f"PREMISE               {card.premise}")
    lines.append(f"QUESTION              {card.question}")
    for i, kp in enumerate(card.key_points):
        head = "KEY POINTS            " if i == 0 else " " * 22
        mark = "✓ verified" if _quote_ok(card, kp) else "✗ NOT VERIFIED"
        lines.append(f'{head}{i + 1}. {kp.statement}   quote: "{kp.quote}"   {mark}')
    adv = []
    for i, ad in enumerate(card.provenance.attribution_advice):
        label = ad.key_point_id or f"kp{i + 1}"
        tag = "" if ad.evidence_verified in (None, True) else " (unverified advice)"
        adv.append(f"{label} {ad.speaker or '?'}{tag}")
    lines.append(f"ATTRIBUTION ADVICE    {' · '.join(adv) or '-'}")
    if card.review.edited:
        lines.append("EDITED                yes (original preserved in review.original)")
    lines.append(MENU)
    return "\n".join(lines)


# --------------------------------------------------------------------------- editing


def editable_fields(card: Card) -> dict:
    return {
        "question": card.question,
        "premise": card.premise,
        "key_points": [{"id": kp.id, "statement": kp.statement, "quote": kp.quote} for kp in card.key_points],
    }


def apply_edit(card: Card, edited: dict) -> Card:
    """Return a copy of the card with the edited fields; spans, source quotes and chunk_ids are recomputed.

    The first edit preserves the unedited card in ``review.original``. A quote that is not found in the
    anchor text is kept as typed with span [0, 0] and no chunk_ids, so validation fails (HC4).
    """
    if not isinstance(edited, dict) or not isinstance(edited.get("key_points"), list):
        raise TypeError("edited file must be a JSON object with 'question', 'premise' and 'key_points'")
    new = card.model_copy(deep=True)
    if new.review.original is None:
        new.review.original = dump(card)
    new.review.edited = True
    if card.type != "false_premise" and str(edited.get("premise") or "").strip():
        raise ValueError("a passage card has no premise; remove the premise from the edit")
    new.question = str(edited.get("question", card.question)).strip()
    prem = edited.get("premise", card.premise)
    new.premise = str(prem).strip() if prem not in (None, "") and card.type == "false_premise" else None
    old = {kp.id: kp for kp in card.key_points}
    kps: list[KeyPoint] = []
    for i, item in enumerate(edited["key_points"]):
        if not isinstance(item, dict):
            raise TypeError("each key point must be an object")
        kid = str(item.get("id") or f"kp{i + 1}")
        prev = old.get(kid)
        typed = str(item.get("quote", prev.quote if prev else "")).strip()
        statement = str(item.get("statement", prev.statement if prev else "")).strip()
        span = textnorm.find_span(typed, card.anchor.text)
        if span is None:
            quote, sp, cids = typed, [0, 0], []
        else:
            quote, sp = card.anchor.text[span[0]:span[1]], [span[0], span[1]]
            cids = [c.passage_id for c in card.anchor.chunks if textnorm.find_span(quote, c.text) is not None]
        kps.append(KeyPoint(id=kid, statement=statement, quote=quote,
                            quote_model=(prev.quote_model if prev else typed), span=sp, chunk_ids=cids))
    new.key_points = kps
    return new


def default_editor(text: str) -> str:
    """Open $EDITOR (fallback nano) on a temp JSON file and return its contents."""
    cmd = shlex.split(os.environ.get("EDITOR") or os.environ.get("VISUAL") or "nano")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "card_edit.json"
        p.write_text(text, encoding="utf-8")
        subprocess.run([*cmd, str(p)], check=True)
        return p.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- session


class _LazyIndex:
    """HC11 QuoteIndex built on first use from the corpus (about 0.7 s) and cached for the session.
    A failed load is remembered too (no retry per edit); ``get`` then returns None."""

    def __init__(self, loader: Callable[[], Corpus]):
        self._loader = loader
        self._done = False
        self._index: QuoteIndex | None = None
        self.error: str | None = None

    def get(self) -> QuoteIndex | None:
        if not self._done:
            self._done = True
            try:
                self._index = QuoteIndex(self._loader().paragraphs)
            except Exception as e:  # noqa: BLE001  provider/corpus problems must not block an edit
                self.error = f"{type(e).__name__}: {e}"
        return self._index


def run_review(
    settings: Settings,
    batch_id: str | None = None,
    *,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
    color: bool = False,
    edit_fn: Callable[[str], str] | None = None,
    validate_card: ValidateCard | None = None,
    now: Callable[[], str] | None = None,
    corpus_loader: Callable[[], Corpus] | None = None,
) -> ReviewResult:
    """Review the pending cards of one batch, one at a time; resumable. Raises ReviewError subclasses."""
    data_dir = settings.data_dir
    validate = validate_card or make_validator(settings)
    editor = edit_fn or default_editor
    uniq = _LazyIndex(corpus_loader or (lambda: load_corpus(settings)))
    stamp = now or (lambda: storage.iso_z(storage.utc_now()))
    style = Style(color)
    batch = pick_batch(data_dir, batch_id)
    lock = storage.FileLock(storage.batch_lock_path(data_dir, batch))
    try:
        lock.acquire()
    except storage.LockError as e:
        raise ReviewLocked(f"batch {batch} is being reviewed by another process ({e})") from e
    result = ReviewResult(batch_id=batch)
    try:
        cards = load_batch_cards(data_dir, batch)
        total = len(cards)
        output_fn(f"Reviewing batch {batch}: {sum(c.review.status == 'pending' for c in cards)} pending of {total}")
        for idx in range(total):
            if cards[idx].review.status != "pending":
                continue
            action = _review_one(cards, idx, total, batch, data_dir, input_fn, output_fn, editor, validate, style, stamp, uniq)
            result.actions.append(f"{cards[idx].card_id}:{action}")
            if action == "quit":
                result.quit = True
                break
        result.approved = sum(c.review.status == "approved" for c in cards)
        result.rejected = sum(c.review.status == "rejected" for c in cards)
        result.pending = sum(c.review.status == "pending" for c in cards)
        result.skipped = sum(a.endswith(':skip') for a in result.actions)
        if result.pending == 0:
            output_fn(f"Batch {batch} fully reviewed: {result.approved} approved, {result.rejected} rejected. Run publish next.")
        else:
            output_fn(f"Stopped: {result.approved} approved, {result.rejected} rejected, {result.pending} still pending. "
                      "Run review again to resume.")
    finally:
        lock.release()
    return result


def _ask(input_fn: Callable[[str], str], prompt: str) -> str | None:
    try:
        return input_fn(prompt)
    except EOFError:
        return None


def _review_one(cards, idx, total, batch, data_dir, input_fn, output_fn, editor, validate, style, stamp, uniq) -> str:
    def save() -> None:
        save_batch_cards(data_dir, batch, cards)

    while True:
        card = cards[idx]
        output_fn("")
        output_fn(render_card(card, idx + 1, total, style))
        raw = _ask(input_fn, "> ")
        if raw is None:
            return "quit"
        cmd = raw.strip().lower()[:1]
        if cmd == "a":
            fails = validate(card)
            if card.review.edited and (index := uniq.get()) is not None:
                fails = fails + uniqueness_failures(card, index)  # HC11 again: an edited card must still pass it
            if fails:
                output_fn("Cannot approve: the card fails validation. Edit it or reject it.\n" + format_failures(fails))
                continue
            card.review.status = "approved"
            card.review.reviewed_at = stamp()
            save()
            return "approve"
        if cmd == "e":
            text = json.dumps(editable_fields(card), indent=2, ensure_ascii=False)
            try:
                edited = apply_edit(card, json.loads(editor(text)))
            except (ValueError, TypeError, OSError, subprocess.CalledProcessError) as e:
                output_fn(f"Edit not applied: {e}")
                continue
            fails = validate(edited)
            index = uniq.get()  # HC11 on the edit path; loaded lazily, once per session
            if index is not None:
                fails = fails + uniqueness_failures(edited, index)
                edited.flags = [f for f in edited.flags if f != "uniqueness_unchecked"]
            else:
                output_fn(f"WARNING: the corpus could not be loaded ({uniq.error}); quote UNIQUENESS (HC11) was "
                          "NOT checked for this edit. The card is flagged 'uniqueness_unchecked'.")
                if "uniqueness_unchecked" not in edited.flags:
                    edited.flags = [*edited.flags, "uniqueness_unchecked"]
            cards[idx] = edited
            save()
            if fails:
                output_fn("Edited card FAILS validation (it cannot be approved until fixed):\n" + format_failures(fails))
            else:
                output_fn("Edit saved; the card passes validation.")
            continue
        if cmd == "r":
            reason = _ask_reason(input_fn, output_fn)
            if reason is None:
                continue
            card.review.status = "rejected"
            card.review.reject_reason = reason
            card.review.reviewed_at = stamp()
            save()
            return "reject"
        if cmd == "s":
            return "skip"
        if cmd == "?":
            output_fn("Reviewer checklist:")
            for i, line in enumerate(CHECKLIST, 1):
                output_fn(f"  {i}. {line}")
            continue
        if cmd == "q":
            return "quit"
        output_fn("Unrecognised command. " + MENU)


def _ask_reason(input_fn, output_fn) -> str | None:
    output_fn("Reject reason:")
    for i, r in enumerate(REJECT_REASONS, 1):
        output_fn(f"  {i}. {r}")
    output_fn(f"  {len(REJECT_REASONS) + 1}. other (free text)")
    output_fn("  (blank to cancel)")
    raw = _ask(input_fn, "reason> ")
    if raw is None or not raw.strip():
        return None
    raw = raw.strip()
    if raw.isdigit():
        n = int(raw)
        if 1 <= n <= len(REJECT_REASONS):
            return REJECT_REASONS[n - 1]
        if n == len(REJECT_REASONS) + 1:
            txt = _ask(input_fn, "other> ")
            return f"other: {txt.strip()}" if txt and txt.strip() else None
        output_fn("Not a valid choice.")
        return None
    return f"other: {raw}"
