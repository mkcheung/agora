"""Seam 1 adapter: chunks from the corpus provider -> Paragraph units (plan section 4.1).

This module and quiz/agora.py are the only places allowed to call common.seams.load.
The adapter never parses source files itself; it consumes whatever the provider returns.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from integrity.common import seams, textnorm
from integrity.common.settings import Settings

REQUIRED_FIELDS = ("author", "work", "work_id", "block_id", "passage_id", "locator", "content_type", "chunk")
INT_FIELDS = ("chapter", "section", "part", "book", "volume", "paragraph", "chunk", "chunk_count", "source_block")
OPTIONAL_FIELDS = (
    "chapter", "section", "part", "book", "volume", "heading", "chapter_title", "section_title",
)
OVERLAP_MIN = 20
OVERLAP_MAX = 400


class CorpusError(Exception):
    """The provider's records break the adapter's contract (exit code 4)."""

    exit_code = 4


class UnknownSourceError(CorpusError):
    """A requested --source is not one of the provider's source files (usage error, exit code 1)."""

    exit_code = 1


@dataclass
class Paragraph:
    """One parser block rebuilt from its chunks."""

    author: str
    work: str
    work_id: str
    source_id: str | None
    block_id: str
    locator: str
    content_type: str
    paragraph: int | None
    position: int
    text: str
    chunks: list[tuple[str, str]]  # (passage_id, chunk_text)
    corpus_version: str | None = None
    source_sha256: str | None = None
    source_file: str | None = None
    context_before: str = ""
    context_after: str = ""
    rebuild_uncertain: bool = False
    work_index: int = 0  # order of first appearance of the work in the corpus
    meta: dict[str, Any] = field(default_factory=dict)  # chapter, section, part, book, volume, heading, ...

    @property
    def chapter(self) -> int | None:
        return self.meta.get("chapter")

    @property
    def section(self) -> int | None:
        return self.meta.get("section")

    @property
    def sort_key(self) -> tuple[int, int]:
        return (self.work_index, self.position)

    def anchor_fields(self) -> dict[str, Any]:
        """Keyword arguments for schema.Anchor (without the skeleton hash)."""
        out: dict[str, Any] = {
            "author": self.author, "work": self.work, "work_id": self.work_id, "source_id": self.source_id,
            "block_id": self.block_id, "locator": self.locator, "paragraph": self.paragraph,
            "position": self.position, "text": self.text,
            "chunks": [{"passage_id": pid, "text": t} for pid, t in self.chunks],
            "context_before": self.context_before, "context_after": self.context_after,
            "corpus_version": self.corpus_version, "source_sha256": self.source_sha256,
            "content_type": self.content_type, "source_file": self.source_file,
        }
        out.update(self.meta)
        return out


@dataclass
class Corpus:
    paragraphs: list[Paragraph]
    report: dict[str, Any]
    corpus_version: str | None

    def by_block_id(self) -> dict[str, Paragraph]:
        return {p.block_id: p for p in self.paragraphs}

    def authors(self) -> list[str]:
        return list(OrderedDict.fromkeys(p.author for p in self.paragraphs))

    def works(self) -> list[tuple[str, str, str]]:
        """(author, work_id, work) in corpus order."""
        return list(OrderedDict.fromkeys((p.author, p.work_id, p.work) for p in self.paragraphs))


# --------------------------------------------------------------------------- rebuild


def _collapse(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _overlap(a: str, b: str) -> int:
    """Largest k with 20 <= k <= 400 and a[-k:] == b[:k]; 0 when there is none."""
    for k in range(min(OVERLAP_MAX, len(a), len(b)), OVERLAP_MIN - 1, -1):
        if a[-k:] == b[:k]:
            return k
    return 0


def rebuild_text(pieces: list[str]) -> tuple[str, bool]:
    """Rebuild a paragraph from its ordered chunk texts by removing the splitter overlap.

    Returns (text, uncertain). Order of attempts per pair: exact overlap; overlap after collapsing
    whitespace; otherwise a single space join and uncertain=True.
    """
    if not pieces:
        return "", True
    text = pieces[0]
    uncertain = False
    for b in pieces[1:]:
        k = _overlap(text, b)
        if k:
            text += b[k:]
            continue
        ca, cb = _collapse(text), _collapse(b)
        k = _overlap(ca, cb)
        if k:
            text = ca + cb[k:]
            continue
        text = text + " " + b
        uncertain = True
    return text, uncertain


# --------------------------------------------------------------------------- conversion


def _int(v: Any) -> Any:
    if isinstance(v, bool):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str) and re.fullmatch(r"-?\d+(\.0+)?", v.strip()):
        return int(float(v))
    return v


def _record(chunk: Any) -> tuple[str, dict[str, Any]]:
    """(text, metadata) from a langchain Document-like object or a mapping."""
    if isinstance(chunk, dict):
        meta = dict(chunk.get("metadata") or {k: v for k, v in chunk.items() if k not in ("text", "page_content")})
        text = chunk.get("page_content", chunk.get("text"))
    else:
        meta = dict(getattr(chunk, "metadata", None) or {})
        text = getattr(chunk, "page_content", None)
        if text is None:
            text = getattr(chunk, "text", None)
    if not isinstance(text, str):
        raise CorpusError(f"chunk {meta.get('passage_id', '?')} has no text")
    return text, meta


def _source_index(report: dict[str, Any]) -> dict[str, tuple[str | None, str | None]]:
    """source_id -> (file, sha256), joined through the report."""
    sha_by_file = {s.get("file"): s.get("sha256") for s in (report.get("manifest") or {}).get("sources", [])}
    out: dict[str, tuple[str | None, str | None]] = {}
    for s in report.get("sources", []):
        f = s.get("file")
        out[s.get("source_id")] = (f, sha_by_file.get(f))
    for f, sha in sha_by_file.items():  # fallback: file name starting with the source id
        for sid in {m for m in [f.split("-")[0].split(".")[0]] if m}:
            out.setdefault(sid, (f, sha))
    return out


def build_paragraphs(chunks: list[Any], report: dict[str, Any], context_chars: int = 300) -> list[Paragraph]:
    """Group chunks by block_id (ordered by chunk), rebuild text, set position and context (section 4.1)."""
    groups: OrderedDict[str, list[tuple[int, str, dict[str, Any]]]] = OrderedDict()
    for ch in chunks:
        text, meta = _record(ch)
        pid = meta.get("passage_id", "?")
        for name in REQUIRED_FIELDS:
            if name not in meta or meta[name] in (None, ""):
                raise CorpusError(f"corpus record {pid} is missing required field {name!r}")
        meta = {k: (_int(v) if k in INT_FIELDS else v) for k, v in meta.items()}
        groups.setdefault(meta["block_id"], []).append((int(meta["chunk"]), text, meta))

    sources = _source_index(report)
    version = report.get("corpus_version")
    paragraphs: list[Paragraph] = []
    position_in_work: dict[str, int] = {}
    work_index: dict[str, int] = {}
    for block_id, items in groups.items():
        items.sort(key=lambda t: t[0])
        first = items[0][2]
        text, uncertain = rebuild_text([t for _, t, _ in items])
        wid = first["work_id"]
        pos = position_in_work.get(wid, 0)
        position_in_work[wid] = pos + 1
        work_index.setdefault(wid, len(work_index))
        f, sha = sources.get(first.get("source_id"), (None, None))
        paragraphs.append(
            Paragraph(
                author=first["author"], work=first["work"], work_id=wid, source_id=first.get("source_id"),
                block_id=block_id, locator=first["locator"], content_type=first["content_type"],
                paragraph=first.get("paragraph") if isinstance(first.get("paragraph"), int) else None,
                position=pos, text=text, chunks=[(m["passage_id"], t) for _, t, m in items],
                corpus_version=first.get("corpus_version", version), source_sha256=sha, source_file=f,
                rebuild_uncertain=uncertain, work_index=work_index[wid],
                meta={k: first[k] for k in OPTIONAL_FIELDS if k in first and first[k] is not None},
            )
        )
    # context from the neighbours in the same work (reading order)
    by_work: dict[str, list[Paragraph]] = {}
    for p in paragraphs:
        by_work.setdefault(p.work_id, []).append(p)
    for plist in by_work.values():
        for i, p in enumerate(plist):
            if i > 0:
                p.context_before = plist[i - 1].text[-context_chars:]
            if i + 1 < len(plist):
                p.context_after = plist[i + 1].text[:context_chars]
    return paragraphs


def _unknown_source_message(provider: Any, requested: list[str], provider_msg: str) -> str:
    """Error text for a rejected --source; lists the valid names from one extra provider call (error path only)."""
    try:
        report = provider(None)[2] or {}
        valid = sorted({x.get("file") for x in (report.get("manifest") or {}).get("sources", []) if x.get("file")})
    except Exception:  # noqa: BLE001  best effort
        valid = []
    msg = f"unknown source {', '.join(map(repr, requested))}"
    return msg + (f"; valid sources: {', '.join(valid)}" if valid else f" ({provider_msg})")


def load_corpus(settings: Settings, sources: list[str] | None = None) -> Corpus:
    """Call the configured corpus provider (seam 1) and convert its chunks to paragraphs."""
    try:
        provider = seams.load(settings.seams.corpus_provider, project_root=settings.project_root)
    except seams.SeamError as e:
        raise CorpusError(str(e)) from e
    try:
        result = provider(sources) if sources else provider()
    except ValueError as e:
        if str(e).startswith("Unknown sources"):  # the provider's own message for a bad --source
            raise UnknownSourceError(_unknown_source_message(provider, sources or [], str(e))) from e
        raise CorpusError(f"corpus provider {settings.seams.corpus_provider} failed: {e}") from e
    except Exception as e:  # provider failures are configuration/corpus problems
        raise CorpusError(f"corpus provider {settings.seams.corpus_provider} failed: {e}") from e
    try:
        chunks, _ids, report = result
    except (TypeError, ValueError) as e:
        raise CorpusError("corpus provider must return (chunks, ids, report)") from e
    paragraphs = build_paragraphs(list(chunks), report or {}, settings.build.context_chars)
    return Corpus(paragraphs=paragraphs, report=report or {}, corpus_version=(report or {}).get("corpus_version"))


class QuoteIndex:
    """Per-work skeleton index used by HC11 (a quote must occur in exactly one paragraph of its work).

    Skeletons are computed once per paragraph; a quote is looked up by a skeleton substring prefilter and
    confirmed with textnorm.count_matches (the same matcher the quiz uses)."""

    def __init__(self, paragraphs: list[Paragraph]):
        self._by_work: dict[str, list[tuple[str, str]]] = {}
        for p in paragraphs:
            self._by_work.setdefault(p.work_id, []).append((textnorm.skeleton(p.text), p.text))

    def count(self, work_id: str, quote: str) -> int:
        """Total valid matches of ``quote`` over all paragraphs of the work (0 when the work is unknown)."""
        q = textnorm.skeleton(quote)
        if not q:
            return 0
        return sum(
            textnorm.count_matches(quote, text) for sk, text in self._by_work.get(work_id, []) if q in sk
        )
