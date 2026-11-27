from collections import Counter

import pytest
from langchain_core.documents import Document

from reader import (
    batch_paragraphs,
    cap_selection,
    is_note,
    list_sections,
    load_work,
    place_notes,
    prep_cache_for_translation,
    select_numbered_sections,
    select_sections,
)


def doc(block_id, text="x", note_of=None, **metadata):
    metadata = {"block_id": block_id, "locator": f"loc {block_id}", "paragraph": 1, **metadata}
    if note_of:
        metadata.update(content_type="note", reference_block_id=note_of)
    else:
        metadata.setdefault("content_type", "prose")
    return Document(page_content=text, metadata=metadata)


def ids(docs):
    return [d.metadata["block_id"] for d in docs]


# --- place_notes ---

def test_notes_follow_their_paragraph_in_original_order():
    docs = [doc("a"), doc("b"), doc("n1", note_of="b"), doc("n2", note_of="a"), doc("n3", note_of="b")]
    assert ids(place_notes(docs)) == ["a", "n2", "b", "n1", "n3"]


def test_note_on_a_note_follows_that_note():
    docs = [doc("a"), doc("b"), doc("n1", note_of="a"), doc("n2", note_of="n1")]
    assert ids(place_notes(docs)) == ["a", "n1", "n2", "b"]


def test_orphan_note_raises():
    with pytest.raises(ValueError, match="missing"):
        place_notes([doc("a"), doc("n1", note_of="gone")])


def test_place_notes_on_every_work_keeps_every_paragraph_once(require_epubs):
    for title in prep_cache_for_translation():
        original = load_work(title)
        placed = place_notes(original)
        assert Counter(ids(placed)) == Counter(ids(original)), title
        position = {d.metadata["block_id"]: i for i, d in enumerate(placed)}
        for i, d in enumerate(placed):
            if is_note(d):
                owner = position[d.metadata["reference_block_id"]]
                # Only the owner's other notes (and their notes) may sit between them.
                assert owner < i and all(is_note(x) for x in placed[owner + 1:i + 1]), (title, i)


# --- list_sections / select_sections ---

def sections_of(title):
    placed = place_notes(load_work(title))
    return placed, list_sections(placed)


def find(sections, prefix):
    matches = [s for s in sections if s.label.startswith(prefix)]
    assert len(matches) == 1, [s.label for s in sections]
    return matches[0]


def test_sections_cover_every_work_without_gaps(require_epubs):
    for title in prep_cache_for_translation():
        placed, sections = sections_of(title)
        assert sections[0].start == 0 and sections[-1].end == len(placed), title
        assert all(a.end == b.start for a, b in zip(sections, sections[1:])), title
        assert sum(s.chars for s in sections) == sum(len(d.page_content) for d in placed), title


@pytest.mark.parametrize("title, prefix", [
    ("Leviathan", "Part I, Chapter 13: OF THE NATURALL CONDITION"),
    ("An Essay Concerning Humane Understanding, Volume 1 / MDCXC, Based on the 2nd Edition, Books 1 and 2",
     "Book II, Chapter 27:"),
    ("An Enquiry Concerning Human Understanding", "Section IV, Part I:"),
    ("Fundamental Principles of the Metaphysic of Morals", "First Section:"),
    ("On Liberty", "Chapter 2: OF THE LIBERTY OF THOUGHT"),
])
def test_known_sections_exist(require_epubs, title, prefix):
    placed, sections = sections_of(title)
    section = find(sections, prefix)
    chosen = select_sections(placed, sections, [section.id])
    assert chosen and not section.unnumbered


def test_front_matter_is_unnumbered(require_epubs):
    _, sections = sections_of("Leviathan")
    assert sections[0].label == "THE EPISTLE DEDICATORY" and sections[0].unnumbered


def test_burke_is_cut_into_paragraph_ranges(require_epubs):
    _, sections = sections_of("Reflections on the Revolution in France")
    assert sections[0].label == "Paragraphs 1–40"
    assert all(s.label.startswith("Paragraphs ") for s in sections)


def test_select_sections_keeps_reading_order_and_rejects_unknown_ids(require_epubs):
    placed, sections = sections_of("On Liberty")
    chosen = select_sections(placed, sections, [sections[3].id, sections[2].id])
    assert chosen == placed[sections[2].start:sections[3].end]
    with pytest.raises(LookupError):
        select_sections(placed, sections, ["s999"])


# --- select_numbered_sections ---

def test_numbered_sections_keep_range_and_notes():
    docs = [doc("a", section=1), doc("b", section=2), doc("n", note_of="b"), doc("c", section=3)]
    assert ids(select_numbered_sections(docs, 2)) == ["b", "n"]
    assert ids(select_numbered_sections(docs, 1, 2)) == ["a", "b", "n"]
    with pytest.raises(LookupError):
        select_numbered_sections(docs, 9)


def test_hume_numbered_section(require_epubs):
    placed = place_notes(load_work("An Enquiry Concerning Human Understanding"))
    chosen = select_numbered_sections(placed, 17)
    assert {d.metadata["section"] for d in chosen} == {17}
    assert any(is_note(d) for d in chosen)  # Hume §17 carries footnote 1


# --- cap_selection / batch_paragraphs ---

def test_cap_keeps_whole_paragraphs_with_notes_and_reports_resume_point():
    docs = [doc("a", "1" * 40), doc("n", "2" * 30, note_of="a"), doc("b", "3" * 40)]
    kept, resume = cap_selection(docs, max_chars=80)
    assert ids(kept) == ["a", "n"] and resume == "loc b"
    assert cap_selection(docs, max_chars=1000) == (docs, None)


def test_cap_always_keeps_first_paragraph():
    docs = [doc("a", "1" * 500), doc("b")]
    kept, resume = cap_selection(docs, max_chars=10)
    assert ids(kept) == ["a"] and resume == "loc b"


def test_batches_never_split_a_paragraph_from_its_notes():
    docs = [doc("a", "1" * 40), doc("n", "2" * 30, note_of="a"), doc("b", "3" * 40), doc("c", "4" * 200)]
    batches = batch_paragraphs(docs, max_chars=100)
    assert [ids(b) for b in batches] == [["a", "n"], ["b"], ["c"]]
    assert [d for b in batches for d in b] == docs
