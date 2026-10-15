from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

CHUNK_SIZE = 2000
CHUNK_OVERLAP = 200
splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)


def make_id(work: str, metadata: dict) -> str:
    # Blocks already identify the source, logical work, XHTML file and position.
    return f"{metadata['block_id']}:c{metadata['chunk']}"


def chunk_paragraphs(paragraphs: list[Document]) -> tuple[list[Document], list[str]]:
    chunks: list[Document] = []
    ids: list[str] = []

    for paragraph in paragraphs:
        # split_documents copies the paragraph's metadata onto every piece, which is now correct
        # because each paragraph belongs to exactly one chapter and section.
        pieces = splitter.split_documents([paragraph])
        for index, piece in enumerate(pieces):
            piece.metadata["chunk"] = index
            piece.metadata["chunk_count"] = len(pieces)
            passage_id = make_id(piece.metadata["work"], piece.metadata)
            piece.metadata["passage_id"] = passage_id
            piece.id = passage_id
            chunks.append(piece)
            ids.append(passage_id)

    # Two records sharing an ID would silently overwrite each other in Pinecone, so fail loudly here.
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate passage IDs in prepared records")
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
