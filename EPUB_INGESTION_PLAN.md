# EPUB Ingestion and Citation Plan

Status: Implemented, validated, uploaded, and activated. See the implementation
record below for results, limitations, and recovery information.

This document consolidates the architect, planner, and compatibility reviews and
the subsequent scope refinements. Creating this document does not run ingestion,
generate embeddings, change query behavior, or upload records.

## Objective

Extend the existing Locke-based pipeline to the seven downloaded EPUBs while
preserving the current question-answering and translation workflows:

- `ask.py`: question → retrieve chunks → assemble context → structured answer →
  verify citations → print.
- `philosophy_query.py`: question → retrieve chunks → translate each passage →
  print the translation with its source location.

Use one shared EPUB pipeline with small structural profiles. Continue using
LangChain `Document` objects and flat metadata. Keep the source manifest in
`ingest.py` and the parsing helpers/profiles in `parsers.py`.

## Current findings

The following counts were observed during the read-only review by running the
existing parser and chunker offline. Nonzero output does not establish complete
or correctly attributed extraction.

| EPUB | Contents | Current paragraphs / chunks | Structural requirements |
| --- | --- | --- | --- |
| `pg7370.epub` | John Locke, *Second Treatise of Government* | 304 / 328 | Book II, 19 chapters, separate chapter titles, and `Sect. N.` paragraphs. Preserve the meaning of existing citations. |
| `pg10615-images-3.epub` | John Locke, *An Essay Concerning Humane Understanding*, Volume 1 | 0 / 0 | Books I–II with restarted chapter numbering, combined chapter/title headings, and numbered section headings in separate paragraphs. |
| `pg3207-images-3.epub` | Thomas Hobbes, *Leviathan* | 0 / 0 | Four parts, 47 numbered chapters, topical subheadings, and authored introduction/conclusion divisions. |
| `pg11224-images-3.epub` | John Stuart Mill, *Utilitarianism* | 94 / 131 | Five chapters, chapter titles in centered HTML blocks, and author notes. |
| `pg27083-images-3.epub` | John Stuart Mill, *The Subjection of Women* | 92 / 174 | Four chapters, cross-file body/footnote relationships, and page anchors. |
| `pg34901-images-3.epub` | John Stuart Mill, *On Liberty* | 0 / 0 | Five chapters with inline titles, footnotes, and a preceding introduction by W. L. Courtney. |
| `pg15679-images-3.epub` | Edmund Burke, *Works*, Volume III | 0 / 0 | Three constituent works, unnumbered divisions, appendices, letters, footnotes, verse quotations, and tables. |

The two newly parsed Mill books currently have `chapter_title=None` throughout
and no numbered sections. Missing optional metadata must be omitted before
Pinecone storage. *The Subjection of Women* also includes `THE END.` in its
current output.

Burke's three principal works are:

- *Speech on the Nabob of Arcot's Debts*, February 28, 1785, with an Appendix.
- *Substance of Speech on the Army Estimates*, February 9, 1790.
- *Reflections on the Revolution in France*.

Their work-boundary anchors are `NABOB_OF_ARCOTS_PRIVATE_DEBTS`,
`SUBSTANCE_OF_THE_SPEECH`, and `REFLECTIONS`. The EPUB collection title belongs in
collection metadata; citations should identify the individual work.

### Existing compatibility constraints

- `parsers.py` reads document-item order, recognizes a narrow chapter pattern,
  and resets important structural state at each XHTML file. All six additional
  EPUBs contain a non-spine `toc.xhtml` navigation document.
- `chunking.py` requires numeric chapters and builds IDs without sufficient
  source, book, or logical-work identity.
- `ingest.py` registers only Locke. Its nominal dry run still contacts Pinecone.
- `retrieval.py` constructs the query embedding/vector store and performs
  similarity search with optional filters. It does not parse books or generate
  answers. Preserve `retrieve(question, num_chunks_to_retrieve=8, filters=None)`.
- `ask.py` requires numeric chapters and verifies citations using
  author/work/chapter/section. That key cannot distinguish repeated chapter
  numbering across books.
- `philosophy_query.py` unconditionally converts the section to an integer when
  printing, so sectionless passages fail.
- Both prompts describe a historical period narrower than the expanded corpus.
- Configuration currently specifies `text-embedding-3-small`, 1024 dimensions,
  and index `agora`. The live index has not been inspected during this review.

## Initial content policy

Include primary works, authored introductions and conclusions, author notes,
and quotations embedded within the primary text. Preserve their actual labels
and relationships.

Exclude navigation, covers, licenses, publisher matter, and Courtney's editorial
introduction by default. Separately authored Burke appendix documents require
verified attribution before inclusion. Enumerate exclusions in the preparation
report; do not attribute excluded or unresolved third-party material to the
EPUB's primary author.

Preserve verse line breaks and meaningful table row/cell relationships. Burke
contains a table in an appendix and another inside the footnotes to
*Reflections*, so excluding supplementary documents does not remove the need to
handle tables in selected author notes. Basic labeled row extraction is enough
for this corpus; its output must remain understandable.

Resolve detached notes through their source references. In *The Subjection of
Women*, a note in one XHTML file refers back to chapter material in the preceding
file. Its location must follow that reference rather than whichever chapter is
active when the note is encountered.

## Source and citation contract

| Field | Purpose |
| --- | --- |
| `author` | Verified author of the selected work or separately attributed document. |
| `work` | Individual cited work title. |
| `source_id` | Stable EPUB/container identifier, such as the Gutenberg identifier. Record the actual input-file fingerprint in the preparation manifest to distinguish revisions. |
| `work_id` | Stable identity for the logical work within its source. |
| `block_id` | Identity of the paragraph or other meaningful source block before splitting. Internal provenance; the LLM does not need to reproduce it. |
| `passage_id` | Unique identity of one chunk after splitting; also its Pinecone vector ID. Store it in chunk metadata. |
| `locator` | Canonical human-readable location, computed during extraction and inherited by chunks. |
| Source position | XHTML href plus an anchor or deterministic block position, sufficient to trace the passage back to the EPUB. |
| Optional structure | Collection, volume, book, part, chapter, chapter title, section, heading, paragraph, content type, and note-reference information where applicable. |

Keep genuine numeric chapter/section values when present. Omit absent optional
values and validate metadata types before upload. Never manufacture chapter
numbers to accommodate the old query schema.

Examples of human-readable locations:

- `Book II, Chapter V, §28`
- `Chapter IV, paragraph 12`
- `Reflections on the Revolution in France, paragraph 12`

Generated paragraph numbers are edition-specific navigation aids, not historical
numbering or printed page numbers. Preserve that distinction in source labels.

## Sequential development blueprint

### 1. Capture representative regression fixtures

Record Locke passages covering chapter/section transitions, split XHTML files,
and Gutenberg boundaries. Preserve their text and citation meaning. Treat the
recorded 304 paragraphs/328 chunks as a reference; explain count changes caused
by corrected extraction rather than requiring old mistakes to remain.

Select focused fixtures for alternate title markup, restarted chapters,
unchaptered works, cross-file notes, editorial attribution, verse, and the
selected footnote table.

### 2. Refactor the common parser and initial chunk identity

Extract one shared EPUB pipeline in `parsers.py`:

- Follow reading-spine order and skip navigation documents.
- Normalize whitespace without destroying meaningful verse/table structure.
- Maintain work/book/part/chapter/section state across XHTML boundaries.
- Reset state when actual structural boundaries require it.
- Extract meaningful blocks with source positions and canonical locators.
- Build an EPUB-wide anchor/reference lookup for detached notes.
- Use small profile functions/settings for the observed heading conventions.

Retain the current 2,000-character chunks and 200-character overlap in
`chunking.py`. Split within meaningful source blocks and preserve all metadata.
Headings provide context rather than isolated tiny chunks. Do not merge across
work, chapter, section, or note boundaries.

Derive each final `passage_id` from source identity, logical work, source block,
and split position. Validate uniqueness across the complete corpus. Identical
inputs and configuration must produce identical records and IDs. New IDs do not
need to match the old generation because migration uses an isolated namespace.

### 3. Adapt the query scripts and prove one complete new-book path

Use *Utilitarianism* first: its alternate chapter-title markup and absent
sections exercise useful differences from Locke. Carry it through parsing,
chunking, context construction, citation verification, translation source
display, and offline preparation. Include a small unchaptered Burke fixture at
this stage so the contract does not accidentally retain mandatory chapters.

In `ask.py`:

- Broaden prompt/help wording to the actual corpus.
- Add the stored `locator` and `passage_id` to context headers.
- Preserve `Citation.author`, `work`, `quote`, and optional `section`; make
  `chapter` optional and add required `passage_id` and `locator`.
- Index retrieved documents by the exact chunk's `passage_id`.
- Check copied source labels and optional chapter/section values against that
  chunk's canonical metadata, then check its quotation.
- Reject empty quotations and require a contiguous excerpt, allowing the
  existing normalization where appropriate.
- Display the stored locator in printed citations.

Preserve `ResearchedResponse`, its `Answer`/`Citations` wrapper, the selected
model, and the retrieve → context → model → verify control flow.

In `philosophy_query.py`, display the stored locator and broaden prompt/help
wording. Preserve translation batching, `ModernizedWork`, and its output fields.
Neither query script needs book-specific parsing rules. Computing the locator
during ingestion avoids an additional structural formatting layer.

### 4. Expand profiles across the remaining sources

After the first path passes its local checks, add the remaining rules:

- Locke's *Essay*: Book I/II boundaries, restarted chapters, and numbered
  paragraph section headings applied to following prose.
- Hobbes: parts, combined chapter/title headings, topical subheadings, and
  authored unnumbered divisions.
- Remaining Mill books: title variants, editorial boundaries, and cross-file
  notes.
- Burke: individual-work anchors, document boundaries, verified attribution,
  selected notes, verse, and tables.

Register all seven sources in the manifest. Allow selected-source preparation
and retries so development need not repeatedly process or upload every book.

### 5. Make default preparation fully offline

Refactor `ingest.py` so record preparation requires neither API credentials nor
network access. Construct remote clients only for explicit remote operations.

Produce one preparation report containing:

- Input-file fingerprints, profile/schema version, chunk settings, and embedding
  configuration identifying the prepared generation.
- Included works and attribution, source-block/chunk counts, and size statistics.
- Sample locators and first/last passages for review.
- Excluded content and its locations/counts.
- Missing metadata, unsupported selected blocks, and duplicate IDs.

Distinguish intentional exclusions from failures. Missing optional titles or
unavailable printed page numbers can produce warnings. Stop preparation for an
empty selected work, ambiguous selected-work boundary, missing required identity
or location, invalid metadata, duplicate IDs, unresolved ownership of a selected
detached note, or selected content that extraction cannot preserve.

Require every selected source to pass preparation before its corpus upload.

### 6. Upload to an explicit staging namespace

Keep the active query namespace separate from the upload destination. Before
embedding, inspect the existing index and verify that its dimension matches the
configured model/dimensions. Retain `text-embedding-3-small` at 1024 dimensions.

Upload the complete revised corpus, including Locke, to a new versioned staging
namespace in the existing index. Use bounded batches, report completed/failed
books or batches, and permit selected retries. Reusing IDs prevents duplicate
stored records but does not prevent repeated embedding charges.

Make vector-store construction namespace-aware while preserving the public
`retrieve` interface. If stores are cached for multiple destinations, namespace
must be part of the cache identity. Staging checks must explicitly address the
staging destination without changing ordinary queries.

Preserve existing vectors and namespaces. Do not use `--reset` for this migration:
it only targets the original `pg7370-chunk-` IDs. After source/parser/chunker
changes, prepare a new corpus generation rather than mixing changed records
with stale records in an active namespace.

### 7. Verify the staged corpus and activate it

Compare uploaded records and fetched metadata samples with preparation output.
Allow for indexing visibility before declaring retrieval failures. Retrieve
representative passages from every included work and exercise repeated
chapters, absent sections, unchaptered works, and a cross-author question.

Run Q&A and translation smoke checks. Manually assess retrieval relevance and
whether cited passages support the answers. Deterministic quotation verification
establishes textual presence, not semantic support for every answer claim.

Activate the compatible query changes and new query namespace together only
after staging passes. Retain the previous corpus and query version/configuration
for recovery. The initial delivery performs no automatic cleanup.

## Expected file changes

| File | Planned responsibility |
| --- | --- |
| `parsers.py` | Shared spine traversal, profile rules, block extraction, attribution, notes, and source locators. |
| `chunking.py` | Existing splitter with general source/block/chunk identity and corpus-wide uniqueness validation. |
| `ingest.py` | Source manifest, offline preparation/reporting, explicit staged upload, bounded batches, and selected retries. |
| `config.py` | Preserve model/index settings and define active query namespace configuration. |
| `retrieval.py` | Namespace-aware store construction; retain similarity search and the existing retrieval interface. |
| `ask.py` | Generic headers, minimally extended citation fields, exact-passage verification, and locator display. |
| `philosophy_query.py` | Generic source display and broader corpus wording; retain translation behavior. |
| Focused tests/fixtures | Verify structural extraction, source identity, offline behavior, and query compatibility. |

### Expected size of the `ask.py` change

Estimate: approximately **40–70 lines changed or added** in the current 176-line
file, including prompt text. This is a planning estimate, not a measured patch.
It excludes tests and ingestion changes.

The changes are concentrated in prompt/CLI wording, `assemble_context`, the
`Citation` fields, verification lookup/checking, and citation printing. The
retrieval call, model configuration, outer response structure, and main workflow
remain.

## Acceptance criteria

- Every included primary work across the seven EPUBs produces traceable chunks.
- Locke text and chapter/section meanings remain correct.
- Essay Book I/Chapter I and Book II/Chapter I remain distinguishable.
- Burke citations identify the constituent work and correct attribution.
- Courtney's introduction is not attributed to Mill.
- Selected detached notes resolve to the correct source references across files.
- Selected verse and table content remains understandable and traceable.
- Chapterless and sectionless passages render and translate without exceptions.
- Metadata is valid, IDs are unique, and identical preparation is repeatable.
- Default preparation succeeds without credentials or network calls.
- Citation checks reject unknown passage IDs, mismatched source labels, empty
  quotations, discontiguous excerpts, and quotations absent from the exact chunk.
- Staged records match preparation results, with representative retrieval from
  every included work before activation.
- Previous corpus data remains available for recovery.

## Deferred work

Retain the current retrieval strategy, model choices, and chunk settings for the
first implementation. Defer reranking, neighbor expansion, automatic work
routing, retrieval diversification, paragraph packing, embedding caches,
automatic index creation, automatic cleanup, elaborate checkpoint orchestration,
and semantic claim verification. Revisit them when retrieval evaluation
demonstrates a concrete need.

## Review checkpoint

The plan was subsequently authorized for execution. The following record
describes the implementation and checks completed against the local EPUBs and
the live Pinecone index.

## Implementation and validation record

Executed on October 14, 2026 (America/Los_Angeles).

### Delivered behavior

- Shared EPUB extraction now supports all seven source files and nine logical
  works, with spine-order traversal, persistent structure across files, linked
  notes, source positions, verse, and selected tables.
- `parse_locke` remains a compatibility wrapper around the shared parser.
- Every stored chunk has deterministic source/block/passage identity and a
  canonical locator. Missing optional metadata is omitted.
- Default ingestion is offline, with source selection, a complete preparation
  report, explicit staged uploads, bounded batches, and recorded retry progress.
- Query retrieval uses the configured namespace and retains its public search
  interface and existing embedding settings.
- `ask.py` retains its response classes and main workflow. Canonical JSON source
  headers reduce source-label ambiguity. The same Groq model runs at temperature
  zero, with bounded provider retries and one citation-correction attempt. The
  verifier still rejects incorrect metadata and noncontiguous or absent quotes;
  it never silently repairs a quotation.
- `philosophy_query.py` retains its translation model and batch workflow, and
  displays native locations without requiring chapters or sections.
- Added the missing `langchain-groq` dependency, its transitive `groq` package,
  focused tests, and usage documentation in `README.md`.

### Prepared and activated corpus

| Source | Source blocks | Chunks |
| --- | ---: | ---: |
| `pg7370.epub` | 309 | 335 |
| `pg11224-images-3.epub` | 94 | 133 |
| `pg10615-images-3.epub` | 746 | 837 |
| `pg3207-images-3.epub` | 1301 | 1417 |
| `pg27083-images-3.epub` | 93 | 175 |
| `pg34901-images-3.epub` | 132 | 216 |
| `pg15679-images-3.epub` | 726 | 825 |
| **Total** | **3401** | **3938** |

The old Locke parser's 304 paragraphs are all retained. Additional blocks include
the authored preface and a verse quotation represented as a one-column table.
The parser also recognizes the source variants `Sect, 10.` and `Sec. 219.`,
correcting their previous assignment to the preceding sections.

Courtney's introduction and the standalone Burke appendix documents remain
excluded. Review additionally identified and excluded Burke's explicitly
editorial/transcriber notes `Footnote_24_24` and `Footnote_75_75`. Exact exclusion
locations are recorded in the preparation report.

Active namespace: **`epub-v1-04b8672ea20df6c7`**.

The original default namespace still contains **328 vectors**. The initial
staging namespace `epub-v1-99c8507c0ba5ab33` contains 3940 vectors and is retained
but inactive. Following the two editorial-note exclusions, the corrected stage
reused embeddings only after comparing each retained passage's text and source
metadata exactly. No second embedding pass was needed for those records.
No vectors or namespaces were deleted.

### Verification completed

- **32 offline tests passed**, including synthetic structural fixtures and the
  real seven-EPUB corpus. Tests cover all 19 Locke chapters and 243 sections,
  Essay book/chapter resets, all 47 Hobbes chapters and four parts, attribution
  exclusions, cross-file notes, selected verse/tables, invalid citation cases,
  offline CLI operation, namespace caching, upload failure/resume, and the
  bounded correction path. Test-only tracing is disabled to keep background
  callbacks offline; runtime project tracing settings are unchanged.
- Ruff checks and `git diff --check` passed.
- The live index dimension was confirmed to be 1024 before embedding.
- All **3938** activated records were fetched and compared against local IDs,
  complete text, and metadata, rather than relying only on record counts.
- Filtered retrieval returned relevant source material from all **nine** works.
  One Arcot result was a short note, while the accompanying results contained
  substantive debt/revenue passages; retrieval ranking remains the existing
  similarity-search strategy.
- Four live Q&A cases passed structured citation checks: Locke, Mill, Burke,
  and a comparison using one passage from Locke and one from Mill. Their final
  citation locations and quotations matched retrieved chunks.
- Two real batched translations completed for Mill and Burke, covering
  sectionless and chapterless source labels.
- The normal `ask.py` CLI was run against the activated default namespace. Its
  answer to the greatest-happiness question printed verified Mill quotations.
- Post-activation index counts confirmed the original 328 vectors were still
  present and the active namespace held exactly 3938 records.

The `ask.py` file is 198 lines, compared with 176 before implementation. Its
actual diff includes prompt/schema changes and the bounded correction helper;
the earlier 40–70-line edit estimate was provisional. The retrieve → context →
structured response → verify → print workflow remains recognizable.

### Evidence and recovery

Generated evidence is local and ignored by Git:

- `reports/epub-preparation.json`: source fingerprints, corpus generation,
  counts, sample locations, and exclusions.
- `reports/epub-v1-04b8672ea20df6c7-progress.json`: acknowledged record IDs and
  embedding-reuse provenance.
- `reports/epub-v1-04b8672ea20df6c7-verification.json`: complete-record comparison
  result and retrieval examples from nine works.
- `reports/epub-v1-04b8672ea20df6c7-live-smoke.json`: final Q&A responses,
  structured citation statuses, and original/translated passages.
- `reports/epub-v1-04b8672ea20df6c7-activation.json`: normal CLI output and final
  namespace counts.
- `reports/before-epub-20261015T045604Z.zip`: the previous tracked Python modules
  and `.gitignore`, without credentials or EPUB contents. The timestamp is UTC.

To review the old corpus, use the previous query code together with the empty
namespace. Changing only the namespace while retaining the new citation schema
does not make old metadata compatible. Preserve both code and destination when
recovering an earlier version.

### Validation limits

The checks establish extraction coverage for these editions, traceable source
locations, metadata integrity, real upload/retrieval, and literal quotation
membership after whitespace/typographic normalization. They do not certify the
semantic support of every answer claim, every inline reference, or translation
fidelity. The model can still produce an invalid quotation after its correction
attempt; that condition remains visible in `ask.py` output.

New EPUBs need a structural/profile review. Supplementary-document attribution
is intentionally conservative. No reranking, automatic work routing, embedding
cache, automatic cleanup, or model replacement was added.
