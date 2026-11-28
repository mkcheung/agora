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


def test_numbered_sections_refuse_to_mix_chapters_after_a_restart():
    docs = [doc("a", section=1), doc("b", section=2), doc("c", section=1)]
    with pytest.raises(ValueError, match="restart"):
        select_numbered_sections(docs, 1)
    assert ids(select_numbered_sections(docs, 2)) == ["b"]


def test_restart_to_the_same_number_in_a_new_chapter_is_caught():
    docs = [doc("a", section=1, chapter=1), doc("b", section=1, chapter=2)]
    with pytest.raises(ValueError, match="restart"):
        select_numbered_sections(docs, 1)


def test_backwards_numbered_range_raises():
    with pytest.raises(ValueError, match="backwards"):
        select_numbered_sections([doc("a", section=3)], 5, 3)


# --- list_sections without EPUBs ---

def test_sections_split_on_chapter_and_keep_labels_unique():
    docs = [
        doc("p", heading="PREFACE"),
        doc("c1", book="Book I", chapter=1, chapter_title="ONE"),
        doc("n", note_of="c1", book="Book I", chapter=1),
        doc("c2", book="Book I", chapter=2),
        doc("ap", book="Book I", heading="Appendix"),
        doc("i", book="Book II"),
        doc("i2", book="Book II"),
    ]
    sections = list_sections(docs)
    assert [(s.label, s.start, s.end, s.unnumbered) for s in sections] == [
        ("PREFACE", 0, 1, True),
        ("Book I, Chapter 1: ONE", 1, 3, False),
        ("Book I, Chapter 2", 3, 4, False),
        ("Book I", 4, 5, False),
        ("Book II", 5, 7, False),
    ]
    assert ids(select_sections(docs, sections, ["s2"])) == ["c1", "n"]


def test_repeated_label_takes_its_heading():
    docs = [doc("a", book="Book IV"), doc("b", book="Book IV", chapter=1), doc("c", book="Book IV", heading="Appendix")]
    assert [s.label for s in list_sections(docs)] == ["Book IV", "Book IV, Chapter 1", "Book IV: Appendix"]


def test_leading_note_joins_first_section_named_after_its_paragraph():
    docs = [doc("n", note_of="gone", chapter=9), doc("a", chapter=1), doc("b", chapter=2)]
    sections = list_sections(docs)
    assert (sections[0].start, sections[0].label) == (0, "Chapter 1")


def test_unstructured_work_is_cut_into_paragraph_ranges(monkeypatch):
    monkeypatch.setattr("reader.PARAGRAPHS_PER_RANGE", 2)
    docs = [doc("a", paragraph=1), doc("n", note_of="a"), doc("b", paragraph=2), doc("c", paragraph=3)]
    sections = list_sections(docs)
    assert [(s.label, s.start, s.end) for s in sections] == [("Paragraphs 1–2", 0, 3), ("Paragraphs 3–3", 3, 4)]


def test_load_work_rejects_unknown_title(monkeypatch):
    monkeypatch.setattr("reader.prep_cache_for_translation", lambda: {"Leviathan": (doc("a"),)})
    assert ids(load_work("Leviathan")) == ["a"]
    with pytest.raises(LookupError, match="Leviathan"):
        load_work("Leviathan II")


def test_section_labels_are_unique(require_epubs):
    for title in prep_cache_for_translation():
        labels = [s.label for s in sections_of(title)[1]]
        assert len(labels) == len(set(labels)), title
