"""Spine-ordered EPUB extraction with small profiles for the current corpus."""

import hashlib
import posixpath
import re
from collections import Counter
from copy import copy
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup, NavigableString, Tag
from ebooklib import epub
from langchain_core.documents import Document

PARSER_VERSION = "1"
ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
CHAPTER_RE = re.compile(r"^CHAPTER\.?\s+([IVXLCDM]+|\d+)\b\.?\s*(.*)$", re.IGNORECASE)
DIVISION_RE = re.compile(r"^(BOOK|PART)\s+([IVXLCDM]+|\d+)\b\.?\s*(.*)$", re.IGNORECASE)
SECTION_RE = re.compile(r"^Sec(?:t)?[.,]\s*(\d+)\.", re.IGNORECASE)
PROFILES = {"pg7370": "treatise", "pg10615": "essay", "pg3207": "hobbes",
            "pg11224": "mill", "pg27083": "mill", "pg34901": "mill",
            "pg15679": "burke"}
BURKE_WORKS = {
    "NABOB_OF_ARCOTS_PRIVATE_DEBTS": "Speech on the Nabob of Arcot's Debts",
    "SUBSTANCE_OF_THE_SPEECH": "Substance of Speech on the Army Estimates",
    "REFLECTIONS": "Reflections on the Revolution in France",
}
# These notes explicitly identify a transcriber or discuss Burke in the third
# person ("Mr. Burke probably had in his mind..."); they are not his prose.
BURKE_EDITORIAL_NOTES = {"Footnote_24_24", "Footnote_75_75"}


def clean(text: str) -> str:
    return " ".join(text.split())


def roman_to_int(numeral: str) -> int:
    if numeral.isdigit():
        return int(numeral)
    numeral = numeral.upper()
    return sum(-ROMAN[a] if ROMAN.get(b, 0) > ROMAN[a] else ROMAN[a]
               for a, b in zip(numeral, numeral[1:] + " "))


def table_text(table: Tag) -> str:
    """Label each data row so table chunks retain the column meanings."""
    rows = [[clean(c.get_text(" ")) for c in row.find_all(["td", "th"], recursive=False)]
            for row in table.find_all("tr")]
    if not rows:
        raise ValueError("Selected table has no rows")
    if any(int(c.get("colspan", 1)) != 1 or int(c.get("rowspan", 1)) != 1
           for c in table.find_all(["td", "th"])):
        raise ValueError("Selected table needs an explicit spanning-cell profile")
    if all(len(row) == 1 for row in rows):
        return "\n".join(row[0] for row in rows if row[0])
    headers = rows[0]
    if any(len(row) != len(headers) for row in rows):
        raise ValueError("Selected table has inconsistent column counts")
    return "\n".join(" | ".join(f"{headers[i] or 'Item'}: {value}"
                               for i, value in enumerate(row))
                     for row in rows[1:] if any(row))


def block_text(element: Tag) -> str:
    element = copy(element)
    for noise in element.select(".x-ebookmaker-pageno, .pagenum, .fnanchor, .fnref, .label"):
        noise.decompose()
    for link in element.find_all("a", href=True):
        if urlsplit(link["href"]).fragment.lower().startswith(("fnanchor", "ref_", "footnote")):
            link.decompose()  # a note's backlink/number is navigation
    if element.name == "table":
        return table_text(element)
    tables = list(element.find_all("table"))
    for table in tables:
        table.replace_with("\n" + table_text(table) + "\n")
    verse = "poem" in element.get("class", []) or element.select_one(".poem") is not None
    if verse:
        for br in element.find_all("br"):
            br.replace_with("\n")
    if verse or tables:
        return "\n".join(clean(line) for line in element.get_text().splitlines() if clean(line))
    return clean(element.get_text(" "))


def blocks(node: Tag):
    """Yield atomic blocks once, including non-paragraph verse and notes."""
    for child in node.children:
        if isinstance(child, NavigableString):
            if clean(str(child)):
                yield "text", child
            continue
        if not isinstance(child, Tag):
            continue
        classes = set(child.get("class", []))
        if child.name in {"script", "style", "nav", "header", "footer", "svg"} or classes & {
            "pg-boilerplate", "x-ebookmaker-cover", "x-ebookmaker-pageno", "pagenum"
        }:
            yield "excluded", child
        elif classes & {"footnote", "note"}:
            yield "note", child
        elif child.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            yield "heading", child
        elif "xhtml_center" in classes:
            yield "title", child
        elif child.name == "a" and child.get("href") and urlsplit(child["href"]).fragment.lower().startswith(("fnanchor", "ref_")):
            yield "note_link", child
        elif child.name in {"p", "pre", "table"} or "poem" in classes or child.name == "li" and not child.find(["p", "table", "ul", "ol"]):
            yield "body", child
        elif child.name in {"img", "hr", "br"}:
            yield "excluded", child
        else:
            yield from blocks(child)


def resolve_href(href: str, target: str) -> str | None:
    parsed = urlsplit(target)
    if parsed.scheme or not parsed.fragment:
        return None
    path = posixpath.normpath(posixpath.join(posixpath.dirname(href), unquote(parsed.path))) if parsed.path else href
    return path + "#" + unquote(parsed.fragment)


def parse_epub(path: str, profile: str | None = None, report: dict | None = None) -> list[Document]:
    book = epub.read_epub(str(path))
    identifiers = book.get_metadata("DC", "identifier")
    match = re.search(r"(?:gutenberg\.org/(?:ebooks/)?|pg)(\d+)",
                      identifiers[0][0] if identifiers else str(path))
    if not match:
        raise ValueError(f"No stable Gutenberg source identifier: {path}")
    source_id = "pg" + match.group(1)
    profile = profile or PROFILES.get(source_id)
    if profile not in {"treatise", "essay", "hobbes", "mill", "burke"}:
        raise ValueError(f"Choose an explicit structural profile for {source_id}")
    creators, titles = book.get_metadata("DC", "creator"), book.get_metadata("DC", "title")
    if not creators or not titles:
        raise ValueError(f"Missing author/work metadata: {path}")
    author, collection = clean(creators[0][0]), clean(titles[0][0])
    documents, notes = [], []
    anchor_docs, references = {}, {}
    exclusions, locations = Counter(), []
    state = {"author": author, "work": collection, "source_id": source_id,
             "work_id": source_id + ":main"}
    if profile == "essay":
        state["volume"] = "Volume 1"
    if profile == "burke":
        state.update(collection=collection, volume="Volume III")
    active, paragraph = False, 0
    last_doc = None
    note_owner = None

    def exclude(reason, href, position, text):
        exclusions[reason] += 1
        locations.append({"reason": reason, "source_href": href,
                          "source_block": position, "preview": clean(text)[:100]})

    def reset(*fields):
        nonlocal paragraph
        for field in fields:
            state.pop(field, None)
        paragraph = 0

    def make_doc(element, text, href, position, metadata, content_type="prose"):
        meta = dict(metadata)
        identity = f"{meta['work_id']}:{href}:{position}"
        meta.update(block_id=meta["work_id"] + ":" + hashlib.sha256(identity.encode()).hexdigest()[:20],
                    source_href=href, source_block=position, content_type=content_type)
        anchor = element.get("id") or next((a["id"] for a in element.find_all(id=True)), None)
        if anchor:
            meta["source_anchor"] = anchor
        return Document(page_content=text, metadata=meta)

    def register(element, href, doc):
        for a in [element] + list(element.find_all(id=True)):
            if a.get("id"):
                anchor_docs[href + "#" + a["id"]] = doc
        for a in element.find_all("a", href=True):
            target = resolve_href(href, a["href"])
            if target:
                references.setdefault(target, doc)

    for ident, linear in book.spine:
        if linear == "no":
            continue
        item = book.get_item_with_id(ident)
        if item is None:
            raise ValueError(f"Missing spine document: {ident}")
        href = item.file_name
        soup = BeautifulSoup(item.get_content(), "html.parser")
        for position, (kind, element) in enumerate(blocks(soup.body or soup), 1):
            raw = clean(element.get_text(" ") if isinstance(element, Tag) else str(element))
            if kind == "excluded":
                exclude("navigation/license/formatting", href, position, raw)
                continue
            if kind == "text":
                if active:
                    raise ValueError(f"Unhandled selected text at {href}:{position}: {raw[:90]}")
                exclude("front matter", href, position, raw)
                continue
            if not raw:
                continue
            upper = raw.upper()
            if kind == "heading":
                chapter, division = CHAPTER_RE.match(raw), DIVISION_RE.match(raw)
                anchor = element.get("id")
                if profile == "burke" and anchor in BURKE_WORKS:
                    reset("chapter", "section", "heading", "chapter_title")
                    state.update(work=BURKE_WORKS[anchor], work_id=source_id + ":" + anchor.lower())
                    active = anchor != "NABOB_OF_ARCOTS_PRIVATE_DEBTS"
                elif profile == "burke" and upper == "SPEECH.":
                    active = True
                elif profile == "burke" and (anchor == "APPENDIX" or upper == "ADVERTISEMENT."):
                    active = False
                elif chapter:
                    reset("section", "section_title", "heading", "chapter_title")
                    state["chapter"] = roman_to_int(chapter.group(1))
                    if chapter.group(2):
                        state["chapter_title"] = chapter.group(2)
                    active = True
                elif division:
                    reset("chapter", "chapter_title", "section", "section_title", "heading")
                    state[division.group(1).lower()] = division.group(1).title() + " " + division.group(2).upper()
                    active = False
                elif upper in {"PREFACE", "THE EPISTLE TO THE READER", "THE INTRODUCTION", "A REVIEW, AND CONCLUSION"}:
                    reset("chapter", "chapter_title", "section", "section_title", "heading", "part")
                    state["heading"] = raw
                    active = True
                elif upper.startswith(("FINIS", "END OF VOL", "THE FULL PROJECT GUTENBERG", "CONTENTS")):
                    active = False
                elif active and not upper.startswith(("FOOTNOTE", "READER,")):
                    if profile == "treatise" and "chapter" in state and element.name == "h3":
                        state["chapter_title"] = raw
                    elif profile == "hobbes" and element.name == "h3" or profile == "burke":
                        state["heading"] = raw
                exclude("structural heading", href, position, raw)
                continue
            if not active:
                exclude("unselected front matter/editorial/appendix", href, position, raw)
                continue
            if kind == "note_link":
                note_owner = anchor_docs.get(resolve_href(href, element["href"]))
                exclude("note navigation", href, position, raw)
                continue
            if kind == "title":
                state["chapter_title"] = raw
                continue
            if kind == "note":
                notes.append((element, href, position, note_owner or last_doc))
                note_owner = None
                continue
            if upper in {"THE END.", "THE END", "FINIS.", "FOOTNOTES:", "FOOTNOTE:"}:
                exclude("end marker", href, position, raw)
                continue
            section = SECTION_RE.match(raw)
            essay_section = re.match(r"^(\d+)\.\s+(.+)$", raw) if profile == "essay" else None
            if essay_section:
                state.update(section=int(essay_section.group(1)), section_title=essay_section.group(2))
                exclude("section heading", href, position, raw)
                continue
            if section:
                state["section"] = int(section.group(1))
            text = block_text(element)
            if not text:
                exclude("empty/navigation block", href, position, raw)
                continue
            paragraph += 1
            meta = dict(state, paragraph=paragraph)
            labels = [str(meta[k]) for k in ("volume", "book", "part") if k in meta]
            if "chapter" in meta:
                labels.append(f"Chapter {meta['chapter']}")
            if "heading" in meta:
                labels.append(meta["heading"])
            if "section" in meta:
                labels.append(f"§{meta['section']}")
            labels.append(f"paragraph {paragraph} (edition-specific)")
            meta["locator"] = ", ".join(labels)
            doc = make_doc(element, text, href, position, meta,
                           "verse" if "poem" in element.get("class", []) else
                           "table" if element.name == "table" else "prose")
            documents.append(doc)
            last_doc = doc
            register(element, href, doc)

    while notes:
        pending = []
        for element, href, position, preceding in notes:
            if profile == "burke" and any(a.get("id") in BURKE_EDITORIAL_NOTES
                                          for a in [element] + list(element.find_all(id=True))):
                exclude("editorial/transcriber note", href, position, element.get_text(" "))
                continue
            targets = [href + "#" + a["id"] for a in [element] + list(element.find_all(id=True)) if a.get("id")]
            owner = next((references[t] for t in targets if t in references), None)
            if owner is None:
                owner = next((anchor_docs[t] for a in element.find_all("a", href=True)
                              if (t := resolve_href(href, a["href"])) in anchor_docs), None)
            if owner is None and "note" in element.get("class", []):
                owner = preceding
            if owner is None:
                pending.append((element, href, position, preceding))
                continue
            text = block_text(element)
            if not text:
                raise ValueError(f"Empty selected note: {href}:{position}")
            meta = {k: v for k, v in owner.metadata.items()
                    if k not in {"block_id", "source_href", "source_block", "source_anchor", "content_type"}}
            label = next((a["id"] for a in element.find_all(id=True)
                          if "footnote" in a["id"].lower()), f"block {position}")
            meta.update(locator=f"Note {label} to {owner.metadata['locator']}",
                        reference_block_id=owner.metadata["block_id"])
            doc = make_doc(element, text, href, position, meta, "note")
            documents.append(doc)
            register(element, href, doc)
        if len(pending) == len(notes):
            raise ValueError(f"Unresolved selected notes: {[(h, p) for _, h, p, _ in pending]}")
        notes = pending

    if not documents:
        raise ValueError(f"No selected body text extracted from {path}")
    if report is not None:
        report.update(source_id=source_id, profile=profile, blocks=len(documents),
                      works=sorted({d.metadata['work'] for d in documents}),
                      exclusions=dict(exclusions), excluded_locations=locations)
    return documents


def parse_locke(path: str) -> list[Document]:
    """Compatibility entry point; the extraction mechanics are shared."""
    return parse_epub(path, "treatise")


if __name__ == "__main__":
    docs = parse_locke("pg7370.epub")
    print(f"Parsed {len(docs)} blocks")
    for doc in docs[:2] + docs[-2:]:
        print(doc.metadata, doc.page_content[:90])
