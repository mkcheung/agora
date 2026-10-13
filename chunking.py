import re
from typing import List, Tuple

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

splitter = RecursiveCharacterTextSplitter(chunk_size=2000, chunk_overlap=200)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def make_id(work: str, metadata: dict) -> str:
    # The ID is the address: work : chapter : section : paragraph : chunk.
    # Section is omitted for works that have none, so the same function serves every book.
    parts = [slugify(work), f"ch{metadata['chapter']:02d}"]
    if "section" in metadata:
        parts.append(f"s{metadata['section']:03d}")
    parts.append(f"p{metadata['paragraph']:03d}")
    parts.append(f"c{metadata['chunk']}")
    return ":".join(parts)


def chunk_paragraphs(paragraphs: List[Document]) -> Tuple[List[Document], List[str]]:
    chunks: List[Document] = []
    ids: List[str] = []

    for paragraph in paragraphs:
        # split_documents copies the paragraph's metadata onto every piece, which is now correct
        # because each paragraph belongs to exactly one chapter and section.
        pieces = splitter.split_documents([paragraph])
        for index, piece in enumerate(pieces):
            piece.metadata["chunk"] = index
            piece.metadata["chunk_count"] = len(pieces)
            chunks.append(piece)
            ids.append(make_id(piece.metadata["work"], piece.metadata))

    # Two records sharing an ID would silently overwrite each other in Pinecone, so fail loudly here.
    duplicates = {i for i in ids if ids.count(i) > 1}
    assert not duplicates, f"Duplicate IDs: {sorted(duplicates)[:5]}"
    return chunks, ids


if __name__ == "__main__":
    from parsers import parse_locke

    paragraphs = parse_locke("pg7370.epub")
    chunks, ids = chunk_paragraphs(paragraphs)
    print(f"{len(paragraphs)} paragraphs -> {len(chunks)} chunks, {len(set(ids))} unique ids")
    print(f"longest chunk: {max(len(c.page_content) for c in chunks)} chars\n")

    split = [(i, c) for i, c in zip(ids, chunks) if c.metadata["chunk_count"] > 1]
    for chunk_id, chunk in split[:3] + [(ids[0], chunks[0]), (ids[-1], chunks[-1])]:
        print(chunk_id, f"({len(chunk.page_content)} chars)")
        print("   ", chunk.page_content[:70], "...")
