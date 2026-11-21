"""Eligibility filters EL-* (plan section 7.2). Every excluded paragraph records every reason that applies."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from integrity.builder.corpus import Paragraph
from integrity.common import sheets, storage
from integrity.common.schema import skeleton_sha256
from integrity.common.settings import Settings

STOPWORDS = frozenset(
    ["a", "about", "after", "all", "also", "an", "and", "any", "are", "as", "at", "be", "been", "but", "by", "can", "could", "did", "do", "does", "for", "from", "had", "has", "have", "he", "her", "him", "his", "how", "i", "if", "in", "into", "is", "it", "its", "me", "more", "my", "no", "not", "of", "on", "one", "or", "our", "out", "she", "so", "some", "such", "than", "that", "the", "their", "them", "then", "there", "these", "they", "this", "those", "to", "up", "was", "we", "were", "what", "when", "which", "who", "will", "with", "would", "you", "your"]
)
LATIN_MARKERS = frozenset(["et", "est", "quod", "enim", "atque", "vel", "nec", "esse"])

OPENERS = ('"', "“", "(*", "(**")
INTRODUCER_RE = re.compile(
    r"(?:his words are|where he says|tells them thus|these words|a little after|in english thus|runs thus)"
    r"\s*[,:]?\s*$",
    re.IGNORECASE,
)
GAP_RE = re.compile(r"\[[^\]]*(?:Greek|dropped|lost|missing)", re.IGNORECASE)
END_CHARS = set(".?!:;\"'”’)]—")
MONEY_RE = re.compile(r"\bl\.\s|\blacs?\b|\bpagodas?\b|\bper cent\b|\blivres\b|\bsterling\b|£", re.IGNORECASE)
BIBLE_BOOKS = (
    "Gen|Exod|Ex|Lev|Num|Deut|Josh|Judg|Ruth|Sam|Kings|Chron|Ezra|Neh|Esth|Job|Psal|Ps|Prov|Eccl|Cant|Isa|Jer|"
    "Lam|Ezek|Dan|Hos|Joel|Amos|Obad|Jon|Mic|Nah|Hab|Zeph|Hag|Zech|Mal|Matt|Mat|Mark|Luke|John|Acts|Rom|Cor|"
    "Gal|Eph|Phil|Col|Thess|Tim|Tit|Heb|Jam|Pet|Jude|Rev"
)
BIBLE_RE = re.compile(r"\(\s*(?:[123]\s*)?(?:" + BIBLE_BOOKS + r")\.?\s+\d+")
EDITORIAL_RE = re.compile(r"^N\.B\.|\bthe editor\b|^Mr\. (?:Fox|Sheridan|Pitt)\b")

REASON_IDS = (
    "EL-type", "EL-len", "EL-rebuild", "EL-lang", "EL-quote-led", "EL-quoted", "EL-introducer", "EL-ibid",
    "EL-gap", "EL-midsentence", "EL-questions", "EL-money", "EL-bible", "EL-editorial", "EL-deny", "EL-used",
)

_OPEN_CLOSE = {"“": "”", "‘": None}


def quoted_ranges(text: str) -> list[tuple[int, int]]:
    """Character ranges inside double quotation marks (curly pairs and straight toggles).

    An unclosed opening quote runs to the end of the paragraph. Single quotes are ignored
    (apostrophes). Straight quotes toggle; curly marks open and close.
    """
    ranges: list[tuple[int, int]] = []
    start: int | None = None
    for i, ch in enumerate(text):
        if ch == "“":
            if start is None:
                start = i
        elif ch == "”":
            if start is not None:
                ranges.append((start, i + 1))
                start = None
        elif ch == '"':
            if start is None:
                start = i
            else:
                ranges.append((start, i + 1))
                start = None
    if start is not None:
        ranges.append((start, len(text)))
    return ranges


def quoted_fraction(text: str) -> float:
    if not text:
        return 0.0
    return sum(e - s for s, e in quoted_ranges(text)) / len(text)


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-zÀ-ɏ']+", text.lower())


def stopword_ratio(text: str) -> float:
    w = _words(text)
    return sum(1 for x in w if x in STOPWORDS) / len(w) if w else 0.0


def latin_markers(text: str) -> int:
    return sum(1 for x in _words(text) if x in LATIN_MARKERS)


def question_fraction(text: str) -> float:
    sentences = [s for s in re.split(r"(?<=[.?!])[\"”’)]*\s+", text.strip()) if s.strip()]
    if not sentences:
        return 0.0
    return sum(1 for s in sentences if s.rstrip("\"”’) ").endswith("?")) / len(sentences)


def ends_with_introducer(text: str) -> bool:
    t = text.rstrip().rstrip("\"“”'‘’ ")
    return bool(INTRODUCER_RE.search(t))


# --------------------------------------------------------------------------- used paragraphs (EL-used)


@dataclass
class UsedIndex:
    """Block ids and skeleton hashes already used by published sheets (incl. retired) and live drafts."""

    block_ids: set[str] = field(default_factory=set)
    skeleton_hashes: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)

    def add(self, block_id: str | None, skel: str | None) -> None:
        if block_id:
            self.block_ids.add(block_id)
        if skel:
            self.skeleton_hashes.add(skel)


def collect_used(data_dir: Path, exclude_batch: str | None = None) -> UsedIndex:
    """Scan every published sheet (retired cards stay in older versions) and every pending/approved draft."""
    used = UsedIndex()
    for v in sheets.list_versions(data_dir):
        try:
            sheet = sheets.load_sheet(data_dir, v)
        except sheets.SheetError as e:
            used.warnings.append(f"sheet {v} skipped: {e}")
            continue
        for c in sheet.cards:
            used.add(c.anchor.block_id, c.anchor.skeleton_sha256)
    drafts = Path(data_dir) / "drafts"
    if drafts.is_dir():
        for bdir in sorted(p for p in drafts.iterdir() if p.is_dir()):
            if exclude_batch and bdir.name == exclude_batch:
                continue
            try:
                rows = storage.read_jsonl(bdir / "cards.jsonl")
            except (OSError, ValueError) as e:
                used.warnings.append(f"draft batch {bdir.name} skipped: {e}")
                continue
            for row in rows:
                if (row.get("review") or {}).get("status", "pending") in ("pending", "approved"):
                    a = row.get("anchor") or {}
                    used.add(a.get("block_id"), a.get("skeleton_sha256"))
    return used


def used_positions(paragraphs: list[Paragraph], used: UsedIndex, neighbor: int) -> set[str]:
    """block_ids excluded by EL-used: used paragraphs and their +-neighbor positions in the same work."""
    by_work: dict[str, list[Paragraph]] = {}
    for p in paragraphs:
        by_work.setdefault(p.work_id, []).append(p)
    out: set[str] = set()
    for plist in by_work.values():
        plist.sort(key=lambda p: p.position)
        for i, p in enumerate(plist):
            if p.block_id in used.block_ids or skeleton_sha256(p.text) in used.skeleton_hashes:
                for j in range(max(0, i - neighbor), min(len(plist), i + neighbor + 1)):
                    out.add(plist[j].block_id)
    return out


# --------------------------------------------------------------------------- evaluation


@dataclass
class Verdict:
    paragraph: Paragraph
    reasons: list[str]
    detail: dict[str, str] = field(default_factory=dict)

    @property
    def eligible(self) -> bool:
        return not self.reasons


def deny_reason(p: Paragraph, settings: Settings) -> str | None:
    for e in settings.eligibility.denylist:
        if e.work_id and e.work_id != p.work_id:
            continue
        if e.block_id and e.block_id != p.block_id:
            continue
        if e.locator_regex and not re.search(e.locator_regex, p.locator):
            continue
        if not (e.work_id or e.block_id or e.locator_regex):
            continue
        return e.reason or "denylist"
    return None


def evaluate(
    paragraphs: list[Paragraph], settings: Settings, used: UsedIndex | None = None
) -> list[Verdict]:
    """Verdict (all applicable reasons) for every paragraph, in corpus order."""
    by_block = {p.block_id: p for p in paragraphs}
    by_work: dict[str, list[Paragraph]] = {}
    for p in paragraphs:
        by_work.setdefault(p.work_id, []).append(p)
    prev: dict[str, Paragraph | None] = {}
    for plist in by_work.values():
        plist.sort(key=lambda p: p.position)
        for i, p in enumerate(plist):
            prev[p.block_id] = plist[i - 1] if i else None
    excluded_used = used_positions(paragraphs, used, settings.build.neighbor_exclusion) if used else set()
    rules_cache: dict[str, dict[str, Any]] = {}
    out: list[Verdict] = []
    for p in paragraphs:
        r = rules_cache.setdefault(p.author, settings.author_rules(p.author))
        text = p.text
        reasons: list[str] = []
        detail: dict[str, str] = {}

        def hit(rid: str, why: str = "", _r: list[str] = reasons, _d: dict[str, str] = detail) -> None:
            _r.append(rid)
            if why:
                _d[rid] = why

        if p.content_type not in r["content_types"]:
            hit("EL-type", p.content_type)
        if not (r["min_chars"] <= len(text) <= r["max_chars"]):
            hit("EL-len", str(len(text)))
        if p.rebuild_uncertain:
            hit("EL-rebuild")
        sr, lm = stopword_ratio(text), latin_markers(text)
        if sr < r["min_stopword_ratio"] or lm > r["max_latin_markers"]:
            hit("EL-lang", f"stopwords={sr:.2f} latin={lm}")
        if text.lstrip().startswith(OPENERS):
            hit("EL-quote-led")
        qf = quoted_fraction(text)
        if qf > r["max_quoted_fraction"]:
            hit("EL-quoted", f"{qf:.2f}")
        pv = prev.get(p.block_id)
        if pv is not None and ends_with_introducer(pv.text):
            hit("EL-introducer")
        if text.rstrip().endswith("Ibid.)"):
            hit("EL-ibid")
        if GAP_RE.search(text):
            hit("EL-gap")
        stripped = text.rstrip()
        if stripped and stripped[-1] not in END_CHARS:
            hit("EL-midsentence", stripped[-20:])
        qfr = question_fraction(text)
        if qfr > r["max_question_fraction"]:
            hit("EL-questions", f"{qfr:.2f}")
        n_money = len(MONEY_RE.findall(text))
        if n_money > r["max_money_terms"]:
            hit("EL-money", str(n_money))
        n_bible = len(BIBLE_RE.findall(text))
        if n_bible > r["max_bible_refs"]:
            hit("EL-bible", str(n_bible))
        if EDITORIAL_RE.search(text):
            hit("EL-editorial")
        d = deny_reason(p, settings)
        if d is not None:
            hit("EL-deny", d)
        if p.block_id in excluded_used:
            hit("EL-used")
        out.append(Verdict(p, reasons, detail))
    del by_block
    return out


def eligible_paragraphs(verdicts: list[Verdict]) -> list[Paragraph]:
    return [v.paragraph for v in verdicts if v.eligible]


def reason_counts(verdicts: list[Verdict]) -> Counter:
    c: Counter = Counter()
    for v in verdicts:
        c.update(v.reasons)
    return c


def normalize_reason(name: str) -> str:
    n = name.strip()
    if n.upper().startswith("EL-"):
        n = n[3:]
    for rid in REASON_IDS:
        if rid[3:].lower() == n.lower():
            return rid
    raise ValueError(f"unknown reason {name!r}; known: {', '.join(REASON_IDS)}")


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)
