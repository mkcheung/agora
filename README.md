# agora

Ask questions about the downloaded philosophical works, or retrieve passages and
translate them into contemporary English. EPUB parsing and upload are separate
from the query scripts.

## Setup and queries

Install the locked dependencies with `uv sync`. Put the relevant API keys in
the ignored `.env` file: `OPENAI_API_KEY`, `PINECONE_API_KEY`, and `GROQ_API_KEY`.
Local preparation and tests do not require those credentials.

```sh
.venv/bin/python ask.py --question "How do Locke and Mill justify limits on political power?"
.venv/bin/python philosophy_query.py --question "What is the greatest happiness principle?"
```

`ask.py` retains its retrieve → context → structured answer → citation
verification workflow. Source headers contain canonical JSON metadata. Each
structured citation names one exact retrieved chunk and its original location.
The verifier checks source labels and a contiguous quotation; it does not prove
that every answer claim follows from that quotation. The same model gets one
correction attempt when checks fail. Remaining failures stay visible in the CLI
output; quotations are never silently repaired.

`philosophy_query.py` retains batched translation and prints the stored source
locations, including passages without chapters or sections.

## Prepare EPUBs offline

```sh
.venv/bin/python ingest.py
.venv/bin/python ingest.py --report reports/epub-preparation.json
.venv/bin/python ingest.py --source pg11224-images-3.epub
```

Default preparation parses, chunks, validates, and reports locally. It makes no
API calls and prints the proposed staging namespace. Repeat `--source` to select
multiple sources. Keep the downloaded EPUBs in the project root; they are
ignored by Git.

The manifest in `ingest.py` selects profiles in `parsers.py`. Most extraction
mechanics are shared: reading-spine order, cross-file structural state, text
normalization, source locations, and linked notes. Add a manifest entry and use
or extend the relevant structural profile when adding another EPUB.

The first corpus includes primary works and selected notes/quotations. It
excludes editorial introductions, unverified standalone appendix documents,
navigation, and licenses. Review exact exclusions in the JSON report. Full
scope and source-specific details are in [EPUB_INGESTION_PLAN.md](EPUB_INGESTION_PLAN.md).

## Stage, verify, and activate

Use the namespace printed by preparation in place of `PRINTED_NAMESPACE` below:

```sh
.venv/bin/python ingest.py --upload --namespace PRINTED_NAMESPACE
.venv/bin/python ingest.py --verify --namespace PRINTED_NAMESPACE
```

Upload checks the existing index dimension before embedding and sends bounded
batches. Its progress report records acknowledged IDs; repeating the same upload
skips acknowledged records. A retry after an unacknowledged request can still
repeat embedding charges. Changed input files or extraction code produce a new
namespace, keeping corpus generations separate.

Verification compares every prepared record's ID, text, and metadata with
Pinecone, then retrieves passages from each logical work. Run question/answer and
translation checks against staging before changing the active destination:

```sh
AGORA_NAMESPACE=PRINTED_NAMESPACE .venv/bin/python ask.py --question "What is the greatest happiness principle?"
```

`DEFAULT_NAMESPACE` in `config.py` selects the active corpus; `AGORA_NAMESPACE`
overrides it for a process. Switching destinations requires a fresh query
process. Keep the compatible query code and namespace together. The original
vectors are preserved; this workflow has no reset or automatic cleanup action.

## Validation and reports

```sh
.venv/bin/python -m pytest -q
.venv/bin/ruff check parsers.py chunking.py ingest.py config.py retrieval.py ask.py philosophy_query.py tests
```

Tests block network access and cover structural continuity, real corpus
hierarchies, attribution exclusions, linked notes, verse/tables, unique IDs,
invalid citations, offline CLI operation, namespaces, and upload failure/retry.
Real-book integration checks are skipped if the ignored EPUB inputs are absent.

Generated reports and a snapshot of the previous query/extraction code are in
the ignored `reports/` directory. See the implementation record in the plan for
the active namespace and live validation results.
