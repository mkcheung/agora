import re

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub
from langchain_core.documents import Document

ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
SECTION_RE = re.compile(r"^Sect\.\s*(\d+)\.")
CHAPTER_RE = re.compile(r"^CHAPTER\.?\s+([IVXLC]+)\.?$")


def roman_to_int(numeral: str) -> int:
    # A smaller numeral before a larger one is subtracted (IV = 4), otherwise added (VI = 6).
    total = 0
    for current, following in zip(numeral, numeral[1:] + " "):
        value = ROMAN[current]
        total += -value if ROMAN.get(following, 0) > value else value
    return total


def clean(text: str) -> str:
    # The source hard-wraps lines; collapse all whitespace runs into single spaces.
    return " ".join(text.split())


def parse_locke(path: str) -> list[Document]:
    book = epub.read_epub(path)
    author = book.get_metadata("DC", "creator")[0][0]
    work = book.get_metadata("DC", "title")[0][0]

    documents: list[Document] = []
    book_label = None

    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), "html.parser")

        chapter = None
        chapter_title = None
        section = None
        paragraph = 0

        for element in soup.find_all(["h2", "h3", "p"]):
            text = clean(element.get_text(" "))

            if element.name == "h2":
                if "PROJECT GUTENBERG" in text.upper() and chapter is not None:
                    break  # license boilerplate starts here; stop reading this file
                if text.startswith("Book "):
                    book_label = text
                match = CHAPTER_RE.match(text)
                if match:
                    chapter = roman_to_int(match.group(1))
            elif element.name == "h3":
                if chapter is not None and chapter_title is None:
                    chapter_title = text
                if text == "FINIS.":
                    break
            elif chapter is not None and text:
                paragraph += 1
                match = SECTION_RE.match(text)
                if match:
                    section = int(match.group(1))

                metadata = {
                    "author": author,
                    "work": work,
                    "chapter": chapter,
                    "chapter_title": chapter_title,
                    "paragraph": paragraph,
                }
                # Pinecone rejects null values, so absent fields are omitted rather than set to None.
                if book_label:
                    metadata["book"] = book_label
                if section is not None:
                    metadata["section"] = section

                documents.append(Document(page_content=text, metadata=metadata))

    return documents


if __name__ == "__main__":
    docs = parse_locke("pg7370.epub")
    print(f"Parsed {len(docs)} paragraphs\n")
    for doc in docs[:3] + docs[40:42] + docs[-2:]:
        print(doc.metadata)
        print("   ", doc.page_content[:90], "\n")
