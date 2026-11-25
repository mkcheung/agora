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

PARSER_VERSION = "4"
ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
CHAPTER_RE = re.compile(r"^CHAPTER\.?\s+([IVXLCDM]+|\d+)\b\.?\s*(.*)$", re.IGNORECASE)
DIVISION_RE = re.compile(r"^(BOOK|PART)\s+([IVXLCDM]+|\d+)\b\.?\s*(.*)$", re.IGNORECASE)
SECTION_RE = re.compile(r"^Sec(?:t)?[.,]\s*(\d+)\.", re.IGNORECASE)
PROFILES = {"pg7370": "treatise", "pg10615": "essay", "pg3207": "hobbes",
            "pg11224": "mill", "pg27083": "mill", "pg34901": "mill",
            "pg15679": "burke", "pg3300": "smith", "pg3420": "wollstonecraft",
            "pg4280": "critique", "pg5682": "groundwork", "pg9662": "hume"}
BURKE_WORKS = {
    "NABOB_OF_ARCOTS_PRIVATE_DEBTS": "Speech on the Nabob of Arcot's Debts",
    "SUBSTANCE_OF_THE_SPEECH": "Substance of Speech on the Army Estimates",
    "REFLECTIONS": "Reflections on the Revolution in France",
}
# These notes explicitly identify a transcriber or discuss Burke in the third
# person ("Mr. Burke probably had in his mind..."); they are not his prose.
BURKE_EDITORIAL_NOTES = {"Footnote_24_24", "Footnote_75_75"}
BURKE_OTHER_SPEAKERS = (
    "MR. BURKE'S SPEECH ON THE REPORT OF THE ARMY ESTIMATES",
    "MR. FOX THEN ROSE", "MR. SHERIDAN THEN ROSE",
    "N.B. AS TO THE PARTICULAR GENTLEMEN", "MR. PITT CONCLUDED THE DEBATE",
)


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
    if element.name == "pre":
        return preserved_lines(element)
    tables = list(element.find_all("table"))
    for table in tables:
        table.replace_with("\n" + table_text(table) + "\n")
    verse = "poem" in element.get("class", []) or element.select_one(".poem") is not None
    if verse:
        for br in element.find_all("br"):
            br.replace_with("\n")
    if verse or tables:
        return "\n".join(clean(line) for line in element.get_text().splitlines() if clean(line))
    return inline_text(element)


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
        elif child.name == "div" and "pre" in classes or child.name in {"p", "pre", "table"} or "poem" in classes or child.name == "li" and not child.find(["p", "table", "ul", "ol"]):
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


NEW_PROFILES = {'smith', 'wollstonecraft', 'critique', 'groundwork', 'hume'}
TITLE_OVERRIDES = {'pg3420': 'A Vindication of the Rights of Woman'}
# Explicitly translator glosses / bibliographic identifications, not Kant's prose.
CRITIQUE_TRANSLATOR_NOTES = {'linknote-28', 'linknote-29', 'linknote-30', 'linknote-31', 'linknote-33', 'linknote-70'}


WOLLSTONECRAFT_VERSE = {'id00116', 'id00119', 'id00142', 'id00177', 'id00255',
                        'id00267', 'id00391', 'id00519', 'id00814', 'id00531'}


def inline_text(element, preserve_lines=False):
    """Keep inline words intact; separate only actual line/block boundaries."""
    node = copy(element)
    for noise in node.select('.x-ebookmaker-pageno, .pagenum, .fnanchor, .fnref, .label, .mnumtag'):
        noise.decompose()
    for link in node.find_all('a', href=True):
        if urlsplit(link['href']).fragment.lower().startswith(('fnanchor', 'ref_', 'footnote', 'linknote-', 'linknoteref-')):
            link.decompose()
    for br in node.find_all('br'):
        br.replace_with('\n')
    for tag in node.find_all(['p', 'div', 'li']):
        tag.insert_before('\n')
        tag.insert_after('\n')
    if preserve_lines:
        return '\n'.join(clean(line) for line in node.get_text().splitlines() if clean(line))
    return clean(node.get_text())


def preserved_lines(element):
    import textwrap
    if element.name == 'div' and element.find(True):
        raise ValueError('Selected div.pre contains markup')
    node = copy(element)
    for link in node.find_all('a', href=True):
        if urlsplit(link['href']).fragment.lower().startswith(('linknote-', 'linknoteref-')):
            link.decompose()
    return '\n'.join(line.rstrip() for line in textwrap.dedent(node.get_text()).splitlines()).strip('\n')


def new_text(element, profile):
    if element.name == 'table':
        return table_text(element)
    if element.name == 'pre' and profile == 'critique' or 'pre' in element.get('class', []):
        return preserved_lines(element)
    if 'poem' in element.get('class', []) or element.select_one('.poem'):
        return block_text(element)
    text = inline_text(element, preserve_lines=profile == 'wollstonecraft' and element.get('id') in WOLLSTONECRAFT_VERSE)
    if profile == 'wollstonecraft':
        text = re.sub(r'^\(\*?Footnote\.\s*', '', text).rstrip(')') if re.match(r'^\(\*?Footnote\.', text) else text
        text = text.replace('*', '').replace('>From', 'From')
    if profile == 'groundwork':
        text = text.replace('*', '').strip()
    if profile == 'hume':
        text = re.sub(r'^Footnote\s+\d+:\s*(?:\(return\))?\s*', '', text)
    return text


def roman_label(number):
    result = ''
    for value, label in ((1000, 'M'), (900, 'CM'), (500, 'D'), (400, 'CD'), (100, 'C'),
                         (90, 'XC'), (50, 'L'), (40, 'XL'), (10, 'X'), (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I')):
        while number >= value:
            result += label
            number -= value
    return result


def profile_heading(profile, element, state, context):
    """Interpret only the printed structures supported by each source edition."""
    text = inline_text(element)
    upper = text.upper()
    def clear(*keys):
        for key in keys:
            state.pop(key, None)
    def division(label):
        clear('division', 'book', 'part', 'chapter', 'chapter_title', 'heading', 'section', 'subheading', 'voice')
        state['division'] = label
        context['base'] = None
        context['active'] = True
    chapter = CHAPTER_RE.match(text)
    if profile == 'smith':
        if upper == 'INTRODUCTION AND PLAN OF THE WORK.':
            state['heading'] = 'Introduction and Plan of the Work'
            context['active'] = True
        elif not context['active']:
            return
        elif match := re.match(r'^BOOK\s+([IVX]+)\.', upper):
            clear('chapter', 'chapter_title', 'heading')
            state['book'] = 'Book ' + match[1]
        elif chapter and element.name == 'h2':
            clear('heading')
            state['chapter'] = roman_to_int(chapter[1])
            state['chapter_title'] = chapter[2]
        elif match := re.match(r'^PART[.\s]+([IVX]+)\b', upper):
            if 'chapter' not in state:
                raise ValueError('Smith PART outside chapter')
            state['heading'] = 'Part ' + match[1]
        elif upper == 'INTRODUCTION.':
            clear('chapter', 'chapter_title')
            state['heading'] = 'Introduction'
        elif upper == 'APPENDIX TO BOOK IV':
            clear('chapter', 'chapter_title')
            state['heading'] = 'Appendix'
        elif upper in {'CONCLUSION.', 'CONCLUSION OF THE CHAPTER.'}:
            state['heading'] = 'Conclusion'
        elif upper.startswith(('CONCLUSION OF THE DIGRESSION', 'APPENDIX TO ARTICLES')):
            pass
        else:
            raise ValueError(f'Unrecognised Smith heading: {text}')
    elif profile == 'wollstonecraft':
        if upper == 'TO' and element.name == 'h4':
            state['heading'] = 'Dedication'
            context['active'] = True
        elif not context['active']:
            return
        elif upper == 'INTRODUCTION.':
            clear('chapter', 'chapter_title', 'section')
            state['heading'] = 'Introduction'
        elif chapter and element.name == 'h4':
            clear('heading', 'chapter_title', 'section')
            state['chapter'] = roman_to_int(chapter[1])
        elif match := re.match(r'^SECTION\s+(\d+)\.(\d+)', upper):
            if int(match[1]) != state.get('chapter'):
                raise ValueError('Wollstonecraft section outside its chapter')
            state['section'] = int(match[2])
        elif state.get('heading') == 'Dedication' and element.name == 'h5' or upper.startswith(('A VINDICATION OF THE RIGHTS OF WOMAN', 'VINDICATION OF THE RIGHTS OF WOMAN')):
            pass
        elif element.name == 'h5' and 'chapter' in state and 'chapter_title' not in state:
            state['chapter_title'] = text
        else:
            raise ValueError(f'Unrecognised Wollstonecraft heading: {text}')
    elif profile == 'groundwork':
        if upper == 'PREFACE':
            division('Preface')
        elif not context['active']:
            return
        elif match := re.match(r'^(FIRST|SECOND|THIRD) SECTION[—.-]+(.*)', text, re.IGNORECASE):
            division(match[1].title() + ' Section')
            state['division_title'] = match[2]
        elif upper == 'THE END':
            context['active'] = False
        elif element.name == 'h2':
            state['subheading'] = text
        else:
            raise ValueError(f'Unrecognised Groundwork heading: {text}')
    elif profile == 'hume':
        if match := re.match(r'^SECTION\s+([IVX]+|\d+)\.?$', upper):
            division('Section ' + roman_label(roman_to_int(match[1])))
            clear('division_title')
        elif not context['active']:
            return
        elif upper == 'INDEX.':
            context['active'] = False
        elif upper == 'FOOTNOTES.':
            pass
        elif element.name == 'h3':
            state['division_title'] = text.rstrip('.')
        elif match := re.match(r'^PART\s+([IVX]+)\.?$', upper):
            state['part'] = 'Part ' + match[1]
        else:
            raise ValueError(f'Unrecognised Hume heading: {text}')
    elif profile == 'critique':
        section = re.search(r'§\s*([IVX]+|\d+)\b', text)
        if match := re.match(r'^PREFACE TO THE (FIRST|SECOND) EDITION', upper):
            division('Preface to the ' + match[1].title() + ' Edition')
        elif not context['active']:
            return
        elif upper == 'INTRODUCTION' and element.name == 'h2':
            division('Introduction')
        elif re.match(r'^(I|II)\. TRANSCENDENTAL DOCTRINE OF (ELEMENTS|METHOD)', upper):
            division('Doctrine of Method' if 'METHOD' in upper else '')
            if not state['division']:
                del state['division']
        elif re.match(r'^(FIRST|SECOND) PART', upper):
            division('Transcendental Aesthetic' if 'ÆSTHETIC' in upper else 'Transcendental Logic')
        elif re.match(r'^(FIRST|SECOND) DIVISION', upper):
            division('Transcendental Analytic' if upper.startswith('FIRST') else 'Transcendental Dialectic')
        elif match := re.search(r'\bBOOK\s+([IVX]+)\b', upper):
            clear('chapter', 'chapter_title', 'heading', 'section', 'voice')
            state['book'] = 'Book ' + match[1]
            context['base'] = None
        elif chapter:
            clear('heading', 'section', 'voice')
            state['chapter'] = roman_to_int(chapter[1])
            state['chapter_title'] = chapter[2]
            context['base'] = None
        elif upper.startswith('APPENDIX'):
            clear('book', 'chapter', 'chapter_title', 'section', 'voice')
            state['heading'] = context['base'] = 'Appendix'
        elif match := re.match(r'^SECTION\s+([IVX]+)\b', upper):
            clear('section', 'voice')
            state['heading'] = context['base'] = 'Section ' + match[1]
        elif re.match(r'^(TRANSCENDENTAL DIALECTIC\W+)?INTRODUCTION\b', upper):
            clear('section', 'voice')
            state['heading'] = context['base'] = 'Introduction'
        elif section:
            pass
        elif match := re.match(r'^([IVX]+)\.\s+(.*)', text):
            clear('section', 'voice')
            base = context.get('base')
            if base == 'Introduction':
                state['heading'] = 'Introduction, Section ' + match[1]
            elif base and base.startswith('Section ') and match[2].startswith('Solution'):
                state['heading'] = base + ', Solution ' + match[1]
            elif state.get('division') == 'Introduction':
                state['heading'] = 'Section ' + match[1]
            else:
                raise ValueError(f'Numbered Critique heading without parent: {text}')
        elif upper == 'TRANSCENDENTAL DOCTRINE OF THE FACULTY OF JUDGEMENT OR, ANALYTIC OF PRINCIPLES':
            clear('heading', 'section', 'voice')
            context['base'] = None
        else:
            raise ValueError(f'Unrecognised Critique heading: {text}')
        if section:
            state['section'] = roman_to_int(section[1])
            if state.get('heading', '').startswith('Section '):
                clear('heading')


def is_run_in(element, raw):
    classes = set(element.get('class', []))
    return element.name == 'p' and not classes & {'poem', 'letter', 'noindent', 'footnote'} and (
        'center' in classes or raw.isupper() and len(raw.split()) <= 12)


def parse_epub(path: str, profile: str | None = None, report: dict | None = None) -> list[Document]:
    book = epub.read_epub(str(path))
    identifiers = book.get_metadata("DC", "identifier")
    match = re.search(r"(?:gutenberg\.org/(?:ebooks/)?|pg)(\d+)",
                      identifiers[0][0] if identifiers else str(path))
    if not match:
        raise ValueError(f"No stable Gutenberg source identifier: {path}")
    source_id = "pg" + match.group(1)
    profile = profile or PROFILES.get(source_id)
    if profile not in {"treatise", "essay", "hobbes", "mill", "burke"} | NEW_PROFILES:
        raise ValueError(f"Choose an explicit structural profile for {source_id}")
    creators, titles = book.get_metadata("DC", "creator"), book.get_metadata("DC", "title")
    if not creators or not titles:
        raise ValueError(f"Missing author/work metadata: {path}")
    author, collection = clean(creators[0][0]), TITLE_OVERRIDES.get(source_id, clean(titles[0][0]))
    new = profile in NEW_PROFILES
    context = {"active": False, "base": None}
    pending_headings, run_ins = [], []
    last_label_path = None
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
            raw = inline_text(element) if isinstance(element, Tag) else clean(str(element))
            if kind == 'body' and profile == 'hobbes' and raw.upper().startswith('TO MY MOST HONOR’D FRIEND'):
                reset('part', 'chapter', 'chapter_title', 'heading', 'section', 'section_title')
                state['heading'] = 'THE EPISTLE DEDICATORY'
                active = True
                exclude('dedication address', href, position, raw)
                continue
            if kind == 'body' and profile == 'mill' and raw.upper().startswith('TO THE BELOVED AND DEPLORED MEMORY'):
                reset('chapter', 'chapter_title', 'heading', 'section', 'section_title')
                state['heading'] = 'DEDICATION'
                active = True
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
            if kind == "heading" and new:
                profile_heading(profile, element, state, context)
                active = context['active']
                if active:
                    pending_headings.append((copy(element), href))
                run_ins.clear()
                exclude("structural heading", href, position, raw)
                continue
            if kind == "heading":
                if profile == 'essay' and upper == 'MY LORD,' and state.get('heading') != 'THE EPISTLE DEDICATORY':
                    reset('chapter', 'chapter_title', 'heading', 'section', 'section_title')
                    state['heading'] = 'THE EPISTLE DEDICATORY'
                    active = True
                    exclude('dedication address', href, position, raw)
                    continue
                if profile == 'mill' and state.get('heading') == 'DEDICATION':
                    state.pop('heading')
                    active = False  # Courtney's introduction follows Mill's dedication.
                if profile in {'essay', 'hobbes'} and state.get('heading') == 'THE EPISTLE DEDICATORY' and upper == 'JOHN LOCKE':
                    exclude('author signature', href, position, raw)
                    continue
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
            if upper in {"THE END.", "THE END", "FINIS.", "FINIS", "FOOTNOTES:", "FOOTNOTE:"}:
                exclude("end marker", href, position, raw)
                continue
            if profile == 'wollstonecraft':
                if raw == 'M. W.' or not raw.replace('*', '').strip():
                    exclude('signature/asterisk rule', href, position, raw)
                    continue
                if re.match(r'^\(\*?Footnote\.', raw):
                    notes.append((element, href, position, last_doc))
                    continue
            if profile == 'groundwork' and element.name == 'pre' and raw.startswith('*'):
                notes.append((element, href, position, last_doc))
                continue
            if profile == 'critique' and element.name == 'p':
                if re.fullmatch(r'§\s*\d+\.?', raw):
                    state['section'] = int(re.search(r'\d+', raw)[0])
                    if state.get('heading', '').startswith('Section '):
                        state.pop('heading')
                    continue
                if is_run_in(element, raw):
                    run_ins.append((element, href))
                    continue
            if profile == 'hume' and (number := element.select_one('.mnum')):
                state['section'] = int(re.search(r'\d+', number.get_text())[0])
            if profile == 'burke' and state['work_id'] == 'pg15679:substance_of_the_speech' and upper.startswith(BURKE_OTHER_SPEAKERS):
                exclude('editor/other speaker', href, position, raw)
                continue
            section = None if new else SECTION_RE.match(raw)
            essay_section = re.match(r'^(\d+)\.(?:\s+(.*))?$', raw) if profile == 'essay' else None
            if essay_section and int(essay_section[1]) > state.get('section', 0):
                state['section'] = int(essay_section[1])
                state.pop('section_title', None)
                if len(raw) < 200:
                    if essay_section[2]:
                        state['section_title'] = essay_section[2]
                    exclude('section heading', href, position, raw)
                    continue
            if section:
                state["section"] = int(section.group(1))
            text = new_text(element, profile) if new else block_text(element)
            if not text:
                exclude("empty/navigation block", href, position, raw)
                continue
            if run_ins:
                text = ' '.join([new_text(e, profile) for e, _ in run_ins] + [text])
            label_path = tuple(state.get(k) for k in ('division', 'volume', 'book', 'part', 'chapter', 'heading', 'section', 'voice'))
            if new and label_path != last_label_path:
                paragraph = 0
            last_label_path = label_path
            paragraph += 1
            meta = dict(state, paragraph=paragraph)
            labels = [str(meta[k]) for k in ("division", "volume", "book", "part") if k in meta]
            if "chapter" in meta:
                labels.append(f"Chapter {meta['chapter']}")
            if "heading" in meta:
                labels.append(meta["heading"])
            if "section" in meta:
                labels.append(f"§{meta['section']}")
            if "voice" in meta:
                labels.append(meta["voice"])
            labels.append(f"paragraph {paragraph} (edition-specific)")
            meta["locator"] = ", ".join(labels)
            doc = make_doc(element, text, href, position, meta,
                           "verse" if "poem" in element.get("class", []) or profile == "wollstonecraft" and element.get("id") in WOLLSTONECRAFT_VERSE else
                           "table" if element.name == "table" or "pre" in element.get("class", [])
                           or profile in {"critique", "hobbes"} and element.name == "pre" else "prose")
            documents.append(doc)
            last_doc = doc
            register(element, href, doc)
            for pending, pending_href in pending_headings + run_ins:
                register(pending, pending_href, doc)
            pending_headings.clear()
            run_ins.clear()

    while notes:
        pending = []
        for element, href, position, preceding in notes:
            if profile == "burke" and any(a.get("id") in BURKE_EDITORIAL_NOTES
                                          for a in [element] + list(element.find_all(id=True))):
                exclude("editorial/transcriber note", href, position, element.get_text(" "))
                continue
            if profile == 'critique' and any(a.get('id') in CRITIQUE_TRANSLATOR_NOTES
                                            for a in [element] + list(element.find_all(id=True))):
                exclude('translator note', href, position, element.get_text())
                continue
            targets = [href + "#" + a["id"] for a in [element] + list(element.find_all(id=True)) if a.get("id")]
            owner = next((references[t] for t in targets if t in references), None)
            if owner is None:
                owner = next((anchor_docs[t] for a in element.find_all("a", href=True)
                              if (t := resolve_href(href, a["href"])) in anchor_docs), None)
            if owner is None and ("note" in element.get("class", []) or profile in {"wollstonecraft", "groundwork"}):
                owner = preceding
            if owner is None:
                pending.append((element, href, position, preceding))
                continue
            text = new_text(element, profile) if new else block_text(element)
            if profile == 'mill':
                text = text.removeprefix(': ')
            if not text:
                raise ValueError(f"Empty selected note: {href}:{position}")
            meta = {k: v for k, v in owner.metadata.items()
                    if k not in {"block_id", "source_href", "source_block", "source_anchor", "content_type"}}
            label = next((a["id"] for a in element.find_all(id=True)
                          if "footnote" in a["id"].lower()), f"block {position}")
            meta.update(locator=f"Note {label} to {owner.metadata['locator']}",
                        reference_block_id=owner.metadata["block_id"])
            if profile == 'wollstonecraft' and element.get('id') in WOLLSTONECRAFT_VERSE:
                meta['literary_form'] = 'verse'
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
