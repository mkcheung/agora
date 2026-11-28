from collections import defaultdict
from dataclasses import dataclass
from functools import cache
from types import MappingProxyType

from langchain_core.documents import Document

from ingest import ROOT, WORKS
from parsers import parse_epub


@cache
def prep_cache_for_translation():
    """Every work's paragraphs by title, parsed once per process.

    The mapping and its tuples are read-only so no caller can change the cached
    corpus; the Documents themselves are shared, so do not edit them in place.
    """
    corpus = defaultdict(list)
    for source in WORKS:
        paragraphs = parse_epub(ROOT / source["file"], source["profile"])

        for paragraph in paragraphs:
            corpus[paragraph.metadata['work']].append(paragraph)

    return MappingProxyType({title: tuple(docs) for title, docs in corpus.items()})

def load_work(title:str):
    corpus = prep_cache_for_translation()
    if title not in corpus:
        raise LookupError(f"{title!r} is not a part of this corpus. Choose one of {sorted(corpus)}")
    return list(corpus[title])


# Default sizes for a translation request, in characters of source text.
MAX_TRANSLATION_CHARS = 30_000  # most text a single request will translate
BATCH_CHARS = 6_000             # most text sent to the model in one call
PARAGRAPHS_PER_RANGE = 40       # section size for works with no chapters (Burke)

# Metadata fields that mark a chapter-level division. Finer levels (§ numbers,
# subheadings inside a chapter) are deliberately left out so a chapter stays one section.
# Same order as the parser's locators ("Book II, Part I"), so labels read alike.
STRUCTURAL_FIELDS = ("division", "book", "part", "chapter")


def is_note(doc: Document) -> bool:
    return doc.metadata.get("content_type") == "note"


def place_notes(paragraphs: list[Document]) -> list[Document]:
    """Move each note so it follows the paragraph (or note) it belongs to.

    The parser emits a work's notes after its last paragraph. Notes keep their
    original relative order, and a note on a note follows that note.
    """
    notes_by_owner = defaultdict(list)
    for doc in paragraphs:
        if is_note(doc):
            notes_by_owner[doc.metadata["reference_block_id"]].append(doc)

    placed = []

    def emit(doc):
        placed.append(doc)
        for note in notes_by_owner.pop(doc.metadata["block_id"], []):
            emit(note)

    for doc in paragraphs:
        if not is_note(doc):
            emit(doc)

    if notes_by_owner:
        orphans = [note.metadata["locator"] for notes in notes_by_owner.values() for note in notes]
        raise ValueError(f"Notes whose paragraph is missing: {orphans}")
    return placed


@dataclass(frozen=True)
class Section:
    id: str            # "s1", "s2", ... in reading order
    label: str         # e.g. "Part I, Chapter 13: OF THE NATURAL CONDITION OF MANKIND"
    start: int         # index of the first paragraph in the placed list
    end: int           # index one past the last paragraph (slice end)
    chars: int         # characters of text, notes included
    unnumbered: bool   # outside the numbered chapters (dedication, introduction, conclusion)


def _section_key(metadata: dict) -> tuple:
    key = tuple((field, metadata[field]) for field in ("volume", *STRUCTURAL_FIELDS) if field in metadata)
    if not any(field in metadata for field in STRUCTURAL_FIELDS):
        key += (("heading", metadata.get("heading")),)
    return key


def _section_label(metadata: dict) -> str:
    parts = []
    for field in STRUCTURAL_FIELDS:
        if field in metadata:
            value = metadata[field]
            parts.append(f"Chapter {value}" if field == "chapter" else str(value))
    if not parts:
        return metadata.get("heading") or metadata["locator"]
    label = ", ".join(parts)
    title = metadata.get("chapter_title") if "chapter" in metadata else metadata.get("division_title")
    return f"{label}: {title}" if title else label


def list_sections(paragraphs: list[Document]) -> list[Section]:
    """Split a placed work (the output of place_notes) into sections in reading order.

    Consecutive paragraphs with the same chapter-level fields form one section. A
    work with no chapter-level fields at all (Burke) is cut into ranges of
    PARAGRAPHS_PER_RANGE paragraphs. Notes stay in their paragraph's section.
    """
    structured = any(field in doc.metadata for doc in paragraphs for field in STRUCTURAL_FIELDS)

    # Find where each section starts: a change of key, or every Nth paragraph.
    starts, key, count = [], None, 0
    for index, doc in enumerate(paragraphs):
        if is_note(doc):
            continue
        if structured:
            new_key = _section_key(doc.metadata)
            if new_key != key:
                starts.append(index)
            key = new_key
        else:
            if count % PARAGRAPHS_PER_RANGE == 0:
                starts.append(index)
            count += 1
    if starts:
        starts[0] = 0  # leading notes, if any, belong to the first section

    sections, used_labels = [], set()
    for number, (start, end) in enumerate(zip(starts, starts[1:] + [len(paragraphs)]), 1):
        span = paragraphs[start:end]
        # starts[0] may be a leading note; name the section after its first paragraph.
        first = next((doc.metadata for doc in span if not is_note(doc)), span[0].metadata)
        if structured:
            label = _section_label(first)
            unnumbered = not any(field in first for field in STRUCTURAL_FIELDS)
        else:
            numbers = [doc.metadata["paragraph"] for doc in span if not is_note(doc)]
            label, unnumbered = f"Paragraphs {numbers[0]}–{numbers[-1]}", False
        # A division can come back after its chapters (Smith's Book IV appendix,
        # Kant's Analytic appendix); name the heading so the labels stay distinct.
        if label in used_labels and first.get("heading"):
            label = f"{label}: {first['heading']}"
        if label in used_labels:
            label = f"{label} ({number})"
        used_labels.add(label)
        sections.append(Section(f"s{number}", label, start, end, _chars(span), unnumbered))
    return sections


def select_sections(paragraphs: list[Document], sections: list[Section], ids: list[str]) -> list[Document]:
    """Return the paragraphs of the chosen sections, in reading order."""
    by_id = {section.id: section for section in sections}
    unknown = [section_id for section_id in ids if section_id not in by_id]
    if unknown:
        raise LookupError(f"Unknown section ids {unknown}. Choose from {list(by_id)}")
    chosen = sorted({by_id[section_id] for section_id in ids}, key=lambda section: section.start)
    return [doc for section in chosen for doc in paragraphs[section.start:section.end]]


def select_numbered_sections(paragraphs: list[Document], first: int, last: int | None = None) -> list[Document]:
    """Keep the paragraphs whose § number (the 'section' field) is in first..last, with their notes.

    § numbers run through the whole work in Hume's Enquiry and Locke's Second
    Treatise, but restart in Locke's Essay, Wollstonecraft, and Kant's Critique, so
    for those pass in a single chapter's paragraphs. A request that matches § numbers
    on both sides of a restart raises ValueError rather than mixing chapters.
    """
    last = first if last is None else last
    if last < first:
        raise ValueError(f"Range §{first}–§{last} runs backwards")
    wanted = f"§{first}" + (f"–§{last}" if last != first else "")
    kept, kept_ids, runs = [], set(), set()
    run, previous, previous_key = 0, None, None
    for doc in paragraphs:
        if is_note(doc):
            keep = doc.metadata["reference_block_id"] in kept_ids
        else:
            number = doc.metadata.get("section")
            keep = isinstance(number, int) and first <= number <= last
            if isinstance(number, int):
                key = _section_key(doc.metadata)
                # A drop in number is a restart; so is the same number in a new chapter
                # (a chapter with only §1 followed by another starting at §1).
                if previous is not None and (number < previous or number == previous and key != previous_key):
                    run += 1
                previous, previous_key = number, key
            if keep:
                runs.add(run)
        if keep:
            kept.append(doc)
            kept_ids.add(doc.metadata["block_id"])
    if not kept:
        raise LookupError(f"No paragraphs numbered {wanted}")
    if len(runs) > 1:
        raise ValueError(f"{wanted} occurs in more than one place because § numbers restart; "
                         "pass in a single chapter's paragraphs")
    return kept


def _units(paragraphs: list[Document]) -> list[list[Document]]:
    """Group each paragraph with the notes that follow it, so the two are never split."""
    units = []
    for doc in paragraphs:
        if is_note(doc) and units:
            units[-1].append(doc)
        else:
            units.append([doc])
    return units


def _chars(docs: list[Document]) -> int:
    return sum(len(doc.page_content) for doc in docs)


def _pack(paragraphs: list[Document], max_chars: int):
    """Yield whole paragraphs (with notes) in groups of at most max_chars, lazily.

    A paragraph longer than max_chars gets a group to itself.
    """
    current, total = [], 0
    for unit in _units(paragraphs):
        size = _chars(unit)
        if current and total + size > max_chars:
            yield current
            current, total = [], 0
        current.extend(unit)
        total += size
    if current:
        yield current


def cap_selection(paragraphs: list[Document], max_chars: int = MAX_TRANSLATION_CHARS) -> tuple[list[Document], str | None]:
    """Keep whole paragraphs (with notes) up to max_chars.

    Returns the kept paragraphs and the locator where reading should resume, or
    None if everything fit. The first paragraph is always kept, even if it alone
    is longer than max_chars.
    """
    groups = _pack(paragraphs, max_chars)
    kept, rest = next(groups, []), next(groups, None)
    return kept, rest[0].metadata["locator"] if rest else None


def batch_paragraphs(paragraphs: list[Document], max_chars: int = BATCH_CHARS) -> list[list[Document]]:
    """Group whole paragraphs (with notes) into batches of at most max_chars.

    A paragraph longer than max_chars gets a batch to itself.
    """
    return list(_pack(paragraphs, max_chars))
