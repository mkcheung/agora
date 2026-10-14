import argparse
import os

from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from pinecone import Pinecone

from chunking import chunk_paragraphs
from config import (
    INDEX_NAME,
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    LEGACY_ID_PREFIX
)
from parsers import parse_locke

load_dotenv()


# One entry per work. Adding a book means adding a parser and an entry here.
WORKS = [
    {"file": "pg7370.epub", "parser": parse_locke},
]


def build_records():
    chunks, ids = [], []
    for work in WORKS:
        work_chunks, work_ids = chunk_paragraphs(work["parser"](work["file"]))
        chunks += work_chunks
        ids += work_ids
    assert len(set(ids)) == len(ids), "IDs collide across works"
    return chunks, ids


def delete_legacy(index) -> int:
    # list() pages through IDs that share a prefix, so only the old upload is touched.
    old_ids = [i for page in index.list(prefix=LEGACY_ID_PREFIX) for i in page]
    for start in range(0, len(old_ids), 100):
        index.delete(ids=old_ids[start:start + 100])
    return len(old_ids)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="delete legacy pg7370-chunk-* vectors first")
    parser.add_argument("--upload", action="store_true", help="embed and upsert (costs API calls)")
    args = parser.parse_args()

    chunks, ids = build_records()
    print(f"Prepared {len(chunks)} chunks from {len(WORKS)} work(s); first id: {ids[0]}")

    index = Pinecone(api_key=os.environ["PINECONE_API_KEY"]).Index(INDEX_NAME)
    legacy = sum(len(page) for page in index.list(prefix=LEGACY_ID_PREFIX))
    print(f"Index '{INDEX_NAME}' holds {legacy} legacy vectors")

    if args.reset:
        print(f"Deleted {delete_legacy(index)} legacy vectors")

    if args.upload:
        embeddings = OpenAIEmbeddings(
            model=EMBEDDING_MODEL,
            dimensions=EMBEDDING_DIMENSIONS,
            show_progress_bar=False,
            chunk_size=50,
            retry_min_seconds=10,
        )
        store = PineconeVectorStore(index_name=INDEX_NAME, embedding=embeddings)
        uploaded = store.add_documents(chunks, ids=ids)
        print(f"Uploaded {len(uploaded)} chunks")
    else:
        print("Dry run: nothing embedded or uploaded. Use --reset and/or --upload.")
