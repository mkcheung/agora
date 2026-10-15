"""Prepare locally by default; explicitly upload/verify an isolated corpus stage."""

import argparse
import hashlib
import json
import math
import time
from collections import Counter
from pathlib import Path

from chunking import CHUNK_OVERLAP, CHUNK_SIZE, chunk_paragraphs
from config import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL, INDEX_NAME
from parsers import PARSER_VERSION, parse_epub

ROOT = Path(__file__).resolve().parent
WORKS = [
    {"file": "pg7370.epub", "profile": "treatise", "works": 1},
    {"file": "pg11224-images-3.epub", "profile": "mill", "works": 1},
    {"file": "pg10615-images-3.epub", "profile": "essay", "works": 1},
    {"file": "pg3207-images-3.epub", "profile": "hobbes", "works": 1},
    {"file": "pg27083-images-3.epub", "profile": "mill", "works": 1},
    {"file": "pg34901-images-3.epub", "profile": "mill", "works": 1},
    {"file": "pg15679-images-3.epub", "profile": "burke", "works": 3},
]
REQUIRED_METADATA = ("author", "work", "source_id", "work_id", "block_id",
                     "passage_id", "locator", "source_href", "source_block", "corpus_version")


def fingerprint(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_records(chunks, ids):
    if not chunks or len(chunks) != len(ids) or len(set(ids)) != len(ids):
        raise ValueError("Prepared records must be nonempty with one unique ID per chunk")
    for chunk, ident in zip(chunks, ids):
        meta = chunk.metadata
        if not chunk.page_content.strip() or len(chunk.page_content) > CHUNK_SIZE:
            raise ValueError(f"Empty or oversized chunk: {ident}")
        if any(key not in meta or meta[key] == "" for key in REQUIRED_METADATA):
            raise ValueError(f"Missing required metadata: {ident}")
        for value in meta.values():
            valid = isinstance(value, (str, bool, int, float)) or (
                isinstance(value, list) and all(isinstance(v, str) for v in value))
            if not valid or (isinstance(value, float) and not math.isfinite(value)):
                raise ValueError(f"Invalid metadata value in {ident}")
        if meta["passage_id"] != ident:
            raise ValueError(f"Passage/vector identity mismatch: {ident}")


def prepare_records(sources=None):
    selected = set(sources or [w["file"] for w in WORKS])
    unknown = selected - {w["file"] for w in WORKS}
    if unknown:
        raise ValueError(f"Unknown sources: {sorted(unknown)}")
    manifest = {
        "parser_version": PARSER_VERSION, "parser_sha256": fingerprint(ROOT / "parsers.py"),
        "chunker_sha256": fingerprint(ROOT / "chunking.py"),
        "chunk_size": CHUNK_SIZE, "chunk_overlap": CHUNK_OVERLAP,
        "embedding_model": EMBEDDING_MODEL, "embedding_dimensions": EMBEDDING_DIMENSIONS,
        "sources": [dict(w, sha256=fingerprint(ROOT / w["file"])) for w in WORKS],
    }
    generation = "epub-v1-" + hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()[:16]
    report = {"corpus_version": generation, "index": INDEX_NAME, "manifest": manifest,
              "selected_sources": sorted(selected), "sources": []}
    chunks, ids = [], []
    for work in WORKS:
        if work["file"] not in selected:
            continue
        details = {"file": work["file"]}
        paragraphs = parse_epub(ROOT / work["file"], work["profile"], details)
        if len(details["works"]) != work["works"]:
            raise ValueError(f"Unexpected logical-work coverage in {work['file']}")
        pieces, piece_ids = chunk_paragraphs(paragraphs)
        for piece in pieces:
            piece.metadata["corpus_version"] = generation
        validate_records(pieces, piece_ids)
        details.update(chunks=len(pieces), content_types=dict(Counter(d.metadata["content_type"] for d in paragraphs)),
                       first={"metadata": pieces[0].metadata, "text": pieces[0].page_content[:180]},
                       last={"metadata": pieces[-1].metadata, "text": pieces[-1].page_content[-180:]})
        report["sources"].append(details)
        chunks.extend(pieces)
        ids.extend(piece_ids)
    validate_records(chunks, ids)
    report.update(chunks=len(chunks), logical_works=len({d.metadata["work_id"] for d in chunks}),
                  longest_chunk=max(len(d.page_content) for d in chunks),
                  mean_chunk_length=round(sum(len(d.page_content) for d in chunks) / len(chunks)),
                  text_characters=sum(len(d.page_content) for d in chunks))
    return chunks, ids, report


def build_records(sources=None):
    chunks, ids, _ = prepare_records(sources)
    return chunks, ids


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    temp.replace(path)


def remote_index():
    # API imports and clients are deliberately outside the offline preparation path.
    from pinecone import Pinecone
    client = Pinecone()
    description = client.describe_index(INDEX_NAME)
    if description.dimension != EMBEDDING_DIMENSIONS:
        raise ValueError(f"Index dimension {description.dimension} != {EMBEDDING_DIMENSIONS}")
    return client.Index(host=description.host)


def upload_records(chunks, ids, report, namespace, batch_size=50, progress_path=None):
    if namespace != report["corpus_version"]:
        raise ValueError("Upload target must equal the prepared corpus's staging namespace")
    if not 1 <= batch_size <= 100:
        raise ValueError("Batch size must be between 1 and 100")
    validate_records(chunks, ids)
    index = remote_index()  # verify index/dimension before constructing embeddings
    progress_path = Path(progress_path or ROOT / "reports" / f"{namespace}-progress.json")
    progress = {"namespace": namespace, "index": INDEX_NAME, "completed_ids": [], "failures": []}
    if progress_path.exists():
        progress = json.loads(progress_path.read_text())
        if progress.get("namespace") != namespace or progress.get("index") != INDEX_NAME:
            raise ValueError("Progress belongs to a different upload destination")
    completed = set(progress["completed_ids"])
    pending = [(doc, ident) for doc, ident in zip(chunks, ids) if ident not in completed]
    if not pending:
        print("All selected records already acknowledged in the upload progress report.", flush=True)
        return progress
    from langchain_openai import OpenAIEmbeddings

    embeddings = OpenAIEmbeddings(model=EMBEDDING_MODEL, dimensions=EMBEDDING_DIMENSIONS,
                                  chunk_size=batch_size, max_retries=2)
    for start in range(0, len(pending), batch_size):
        batch = pending[start:start + batch_size]
        try:
            values = embeddings.embed_documents([doc.page_content for doc, _ in batch])
            if len(values) != len(batch) or any(len(v) != EMBEDDING_DIMENSIONS for v in values):
                raise ValueError("Embedding response does not match the prepared records")
            response = index.upsert(vectors=[{"id": ident, "values": value,
                                              "metadata": dict(doc.metadata, text=doc.page_content)}
                                             for (doc, ident), value in zip(batch, values)],
                                    namespace=namespace)
            if response.upserted_count != len(batch):
                raise ValueError("Pinecone did not acknowledge the complete batch")
        except Exception as exc:
            progress["failures"].append({"ids": [ident for _, ident in batch], "error": type(exc).__name__})
            save_json(progress_path, progress)
            raise
        completed.update(ident for _, ident in batch)
        progress["completed_ids"] = sorted(completed)
        save_json(progress_path, progress)
        print(f"Acknowledged {start + len(batch)}/{len(pending)} pending chunks in {namespace}", flush=True)
    return progress


QUESTIONS = {
    "pg7370": "How is political power different from paternal power?",
    "pg10615": "Does Locke believe that people have innate principles?",
    "pg11224": "What is the greatest happiness principle?",
    "pg27083": "Why does Mill oppose the legal subordination of women?",
    "pg3207": "Why do people authorize a sovereign to maintain peace?",
    "pg34901": "When may society interfere with individual liberty?",
    "pg15679:nabob_of_arcots_private_debts": "How do the Nabob of Arcot's debts affect the Carnatic?",
    "pg15679:substance_of_the_speech": "What does Burke say about the French Revolution and the British constitution?",
    "pg15679:reflections": "Why does Burke criticize the French Revolution?",
}


def verify_namespace(chunks, ids, report, namespace, attempts=12, interval=5):
    if namespace != report["corpus_version"]:
        raise ValueError("Verification target does not match the prepared corpus")
    if len(report["selected_sources"]) != len(WORKS):
        raise ValueError("Verify the full corpus before activation")
    index = remote_index()
    for attempt in range(attempts):
        stats = index.describe_index_stats()
        entry = stats.namespaces.get(namespace)
        count = entry.vector_count if entry else 0
        if count == len(ids):
            break
        if attempt == attempts - 1:
            raise ValueError(f"Staged count {count} != prepared count {len(ids)}")
        time.sleep(interval)
    # Fetch every record's ID. Compare complete text and metadata for each record,
    # not just count/samples: this detects a successful count with wrong contents.
    for start in range(0, len(ids), 100):
        expected = dict(zip(ids[start:start + 100], chunks[start:start + 100]))
        fetched = index.fetch(ids=list(expected), namespace=namespace).vectors
        if set(fetched) != set(expected):
            raise ValueError("Staging is missing prepared vector IDs")
        for ident, doc in expected.items():
            metadata = dict(fetched[ident].metadata)
            if metadata.pop("text", None) != doc.page_content or metadata != doc.metadata:
                raise ValueError(f"Round-trip metadata/text mismatch: {ident}")
    from retrieval import get_vectorstore

    store = get_vectorstore(namespace)
    results = []
    work_docs = {doc.metadata["work_id"]: doc for doc in chunks}
    for work_id, example in work_docs.items():
        question = QUESTIONS.get(work_id, QUESTIONS.get(example.metadata["source_id"]))
        docs = store.similarity_search(question, k=3, filter={"work_id": work_id})
        if not docs or any(d.metadata.get("work_id") != work_id for d in docs):
            raise ValueError(f"No correctly attributed retrieval for {work_id}")
        for doc in docs:
            validate_records([doc], [doc.metadata["passage_id"]])
        results.append({"work_id": work_id, "question": question,
                        "passages": [{"id": d.metadata["passage_id"], "locator": d.metadata["locator"],
                                      "text": d.page_content} for d in docs]})
    return {"namespace": namespace, "verified_records": len(ids), "retrieval": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", choices=[w["file"] for w in WORKS],
                        help="prepare/upload selected sources; repeat for more than one")
    parser.add_argument("--report", type=Path, help="write the full offline JSON report")
    parser.add_argument("--upload", action="store_true", help="embed/upsert to an explicit staging namespace")
    parser.add_argument("--verify", action="store_true", help="verify staged records and retrieval; no activation")
    parser.add_argument("--namespace", help="explicit staging destination printed by preparation")
    parser.add_argument("--batch-size", type=int, default=50)
    args = parser.parse_args()
    if (args.upload or args.verify) and not args.namespace:
        parser.error("--upload/--verify require an explicit --namespace")
    if args.verify and args.source:
        parser.error("--verify requires the complete corpus")
    chunks, ids, report = prepare_records(args.source)
    print(f"Prepared {len(chunks)} chunks from {len(report['sources'])} sources / {report['logical_works']} works")
    for source in report["sources"]:
        print(f"  {source['file']}: {source['blocks']} blocks -> {source['chunks']} chunks; {source['content_types']}")
    print(f"Staging namespace: {report['corpus_version']}", flush=True)
    if args.report:
        save_json(args.report, report)
    if args.upload:
        upload_records(chunks, ids, report, args.namespace, args.batch_size)
    if args.verify:
        verification = verify_namespace(chunks, ids, report, args.namespace)
        save_json(ROOT / "reports" / f"{args.namespace}-verification.json", verification)
        print(f"Verified {verification['verified_records']} records and {len(verification['retrieval'])} works")
    if not (args.upload or args.verify):
        print("Offline preparation only: no API clients, embeddings, or uploads.")


if __name__ == "__main__":
    main()
