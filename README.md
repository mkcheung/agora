# agora

Ask questions about the downloaded philosophical works using original passages
and checked citations. The query graph can modernize its answer. EPUB parsing and upload are separate
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

`philosophy_query.py` classifies questions, retrieves and grades passages, and
generates answers with citations before modernizing the answer.

## Prepare EPUBs offline

```sh
.venv/bin/python ingest.py
.venv/bin/python ingest.py --report /tmp/agora-preparation-review.json
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
repeat embedding charges. Changed source files, parser, chunker, embedding inputs or embedding settings
produce a new namespace. Uploads refuse the default and active namespaces.
Reports accept identical reruns and refuse different content at the same path.

Verification compares every prepared record's ID, text, and metadata with
Pinecone, then retrieves passages from each logical work. Run question/answer and
answer-modernization checks against staging before changing the active destination:

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

New-book paragraph counters restart at each printed label path; the original
profiles count across section changes within a chapter. All paragraph numbers
are edition-specific. The twelve Gutenberg sources contain fourteen works by
eight authors. Sam Harris remains deferred. See CORPUS_UPGRADE_PLAN.md for the
generation and review sequence. Tables are preserved as tables and translator
material is excluded from author-attributed passages.

## Modern-English edition (drafts)

The edition reads original parser blocks offline and keeps translations outside
Pinecone. Model calls require an explicit cumulative cap; the default is $10.
The append-only spend ledger includes reservations for in-flight or unknown-cost
calls and survives retries, restarts and changes of edition ID. Eight bounded
workers share that ledger. Standard price estimates are recorded in edition.py;
OpenAI input charges are conservatively booked at the cache-write upper rate.

```sh
.venv/bin/python edition.py plan
.venv/bin/python edition.py pilot --max-usd 2
.venv/bin/python edition.py build --max-usd 8
.venv/bin/python edition.py judge --max-usd 10
.venv/bin/python edition.py check
.venv/bin/python edition.py read --work pg7370:main --chapter 5
```

The lower build cap leaves room for judging under the same total ledger. A cap
stop preserves completed records; run the same command to resume with a larger
explicit cap. Short packs share calls within a chapter; tables stay verbatim.
`check` reports stale, moved and orphan records against the fresh parse. Notes
appear beside their owners in the CLI reader. Flags and judge disagreements
remain unresolved until reviewed; a partial or flagged draft is never a released
edition. Back up the ignored `editions/drafts/` directory after paid work.

The frozen translation prompt and separately hashed rules live in
`edition_prompts/`. Prompt drift is checked with AST without importing the query
graph. Streamlit and searching modern text remain later work in the plan.
