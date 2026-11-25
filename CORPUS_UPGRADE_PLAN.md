# Corpus Upgrade Plan

**Execution status (2026-11-25): upload and application-switch phase complete on `main`.** The verified final G4 corpus contains all 14 works and 8,936 records. Default namespace and R1 author routing were committed as `40a26d7` and fast-forward merged from `corpus-upgrade` into `main`. One real Kant application question passed all ten flow assertions; all 637 offline tests passed after activation. Paid integrity grading remains stopped, and completed v002 evaluations must not be repeated. No remote push or service restart was performed. The cosmetic display wrapper-tag issue is recorded; modern-English edition work and R7/v003 remain separate and deferred. See `CORPUS_UPGRADE_STATE.json`.

**Edition scope agreed during execution:** use the suggested models with a $10 cumulative cap and stop with a resumable partial edition. The 92-block pilot is saved; all required bound judge receipts are now present, cumulative booked spend is $1.600150, and 48 renderings still require review. Flagged renderings remain unreleased drafts. The current source/render/judge review packet is `reports/edition-review-current-20261125.json`.

**Goals**
1. Let `philosophy_query.py` answer questions about each author's ideas from that author's own works: 12 Gutenberg books by 8 authors. Sam Harris is deferred.
2. Produce a modern-English edition of every work, paragraph by paragraph, that you can read side by side with the original.
3. Make the existing pipeline sturdier, and improve its results.

**How this was produced**
1. Five research agents examined the code and all twelve EPUBs offline, with no uploads and no API calls.
2. Three of them proved their parser rules on throwaway copies of `parsers.py` (Appendix C).
3. An adversarial reviewer attacked revision 1 and reported 19 findings, which this revision resolves (§13).
4. The reviewer re-checked revision 2: 16 findings resolved, 3 partly resolved, and 6 new ones. Revision 3 fixes all of them.
5. A final targeted check confirmed every fix against the code. Its one NIT is applied (§13).

---

## 0. How to read this plan

**Ownership**
- `philosophy_query.py` is yours. Nothing in it changes without your OK (§8).
- Everything else can be done by you or by Claude, item by item.

**Generations**
- Every change to the library's contents produces a new Pinecone namespace, called a *generation*.
- Your integrity manual's first rule of thumb (`integrity/MANUAL.md` §9) is "change one thing in Agora at a time, then run the quiz". So the plan has three generations:
  - **G1** adds the books;
  - **G2** fixes the current books' text;
  - **G3** changes what gets embedded.
- Embedding one generation is about 2 million tokens, a few cents at text-embedding-3-small's list price.

**Comparing quiz runs**
- Compare only runs on the same sheet and the same grader version.
- Always pass `--sheet` and `--namespace` explicitly. Otherwise `quiz` uses the latest sheet (`integrity/quiz/preflight.py:120`) and the active namespace.
- Put the older run first in `compare <older> <newer>`. The output reads "COMPARE a -> b" (`integrity/quiz/report.py:371`), so the reverse order makes a regression look like a gain.
- The current baseline is `r-20261121-172125`: sheet v001, grader `g-eaa3d7`, Found 22/23, Complete 54/58, Faithful 297/304.

**Deletion.** Nothing is deleted until a newer generation has been active and re-baselined (§11).

## 1. What "done" looks like
1. The active namespace holds 12 books / 14 works.
   - Every paragraph's locator matches the printed book.
   - No editor's, translator's or other speaker's words carry the author's name.
2. With §8 R1, questions naming Kant, Hume or Wollstonecraft are answered from their own books.
3. Every generation is measured on an unchanged answer sheet, and no drop goes unexplained.
4. A modern-English edition of all 14 works is checked for faithfulness and readable in a CLI reader, and later in Streamlit.
5. The dangerous mistakes in §11 are blocked by code, not by memory.

---

## 2. What we found

### 2.1 The pipeline works and is reproducible

**Reproducibility.** Offline preparation of today's code plus the 7 EPUBs reproduces the live namespace `epub-v1-04b8672ea20df6c7` exactly: 3,401 paragraph blocks, 3,938 chunks, 3.84M characters. All 32 integrity cards resolve.

**What holds**
- The namespace is a hash of a manifest: parser and chunker file hashes, chunk settings, embedding model, and every source file's hash (`ingest.py:56-63`).
- Uploads to any other namespace are refused (`:116-117`).
- Uploads resume from a progress file (`:122-129`).
- Verify fetches every record and compares text and metadata exactly (`:190-198`).

**Gaps**
1. **The manifest doesn't cover what gets embedded.** `ingest.py` is not hashed. If the embedding input changed but the parser didn't, the computed namespace would be the *live* one. The progress file would then make the upload silently do nothing; without that file, the upload would overwrite live vectors.
2. **Nothing stops an upload into the active namespace.**
3. **A missing `QUESTIONS` entry is found late.** It only surfaces at the end of `--verify` (`:205-206`), after the paid upload.
4. **Verify's relevance check is weak.** It accepted the 19-character note "The Nabob of Arcot." as a work's top result.
5. **Whole numbers aren't enforced.** `chapter` and `section` must be whole numbers, because `ask.py:78` calls `int()` on them and `verify_citations` compares exactly. But `validate_records` accepts any number or string (`ingest.py:42-46`).
6. **Leftover index state** (per `reports/`):
   - the staging namespace `epub-v1-99c8507c0ba5ab33`, with 3,940 vectors in its progress file;
   - 328 legacy vectors in the default namespace `""`.

   There is no delete command.
7. **Report files can be overwritten.**
   - The namespace doesn't depend on `--source`, so a one-book preparation report can overwrite the full one.
   - The README's example `--report reports/epub-preparation.json` (`README.md:33`) would overwrite the live generation's report.
8. **Outside git:** the EPUBs (`*.epub`), `reports/` (including the progress files that make uploads resumable), and every quiz run's raw files.

**Stale code and docs**
- **A test for removed code.** `tests/test_epub_pipeline.py:360-379` imports `ModernizedWork` from `philosophy_query.py`, which commit `bf7c232` removed. The suite: 31 pass, 1 fails. `reports/run_live_checks.py` has the same stale import.
- **README out of date:**
  - its scope paragraph;
  - the claim that only extraction changes make a new namespace;
  - the "translation checks" wording (`README.md:67-68`).
- **Reversed compare order.** MANUAL §6.1 (line 351) shows `compare latest <baseline>`, which reads backwards (see §0).
- **`tools.py` would fail if used:**
  - `retrival` (line 16);
  - `parse_docstrings`, but langchain-core only has the singular;
  - `get_by_ids`, which langchain-pinecone 0.2.13 doesn't implement.

  This matters before roadmap step 4, not for this upgrade.

### 2.2 Retrieval quality today
- **Only paragraph text is embedded** (`ingest.py:140`). 88.6% of chunks have a chapter title, heading or section title that search never sees. That includes Leviathan's 730 headings and the Essay's 618 marginal summaries.
- **Unfiltered search can't tell authors apart.** Baseline card `c-9f28da273c` asked about Hobbes, and none of its 8 retrieved passages were Hobbes's.
- **Fragments count as evidence.** 161 chunks under 80 characters ("Appendix, No. 7 .", "Sinne What") can count toward `decide_to_generate`'s three-passage threshold.
- **Paragraphs split mid-sentence.** 462 blocks are split into several chunks. 524 of the 537 split points fall mid-sentence, and the continuation chunks lose labels such as "Sect. N.".
- **The prefix experiment.** It used a small local embedding model in place of OpenAI's, so treat it as indicative only.
  - Prefixing chunks of 200+ characters with author, work and headings raised unfiltered quiz Found@8 from 12/23 to 19/23.
  - MMR made results worse.

### 2.3 The current seven books have fixable defects
| Book | Defect | Effect |
|---|---|---|
| Locke, *Essay* | The essay rule (`parsers.py:253-255`) treats every paragraph starting "N. " as a section heading | 9 real paragraphs (5,738 characters) are dropped; 4 blocks carry the wrong § |
| Burke, Army Estimates speech | Paragraphs 1, 38, 40, 42 and 43 are the editor's preface, Fox, Sheridan, a reporter's N.B., and Pitt | ask.py can cite them as Burke. Integrity already avoids them |
| *Essay*, *Leviathan*, *On Liberty* | The dedications are dropped: Epistle Dedicatory (4,788 characters), Godolphin (2,169), Mill's (901) | Author text is missing |
| 6 of the 7 books | `get_text(" ")` (`parsers.py:81`, `:189`) inserts spaces at inline tags ("us . We"). It also splits 88 words at Burke's page anchors ("au thority") | 317 blocks |
| *Leviathan*, *Subjection* | A bare "FINIS" is kept (the end set at `parsers.py:249` has only "FINIS."); 3 Mill notes start with ": " | Small junk |

### 2.4 The five new books can't be ingested as is
| Book | Today's parser | Prototype |
|---|---|---|
| Smith, *Wealth of Nations* (pg3300) | Raises on a `div.pre` table. With the tables skipped, it drops 1,111 of 2,089 blocks and mislabels ("Book I, Part II, Chapter 11") | 2,098 blocks (10 of them tables) → 2,391 chunks |
| Wollstonecraft, *Vindication* (pg3420) | Labels the editor's biography, the dedication and the Introduction as "Chapter 13", and attributes the biography to her | 764 blocks (22 notes) → 771 chunks; biography excluded |
| Kant, *Critique* (pg4280) | Drops both Prefaces, the Introduction and the Aesthetic (169 blocks); labels the Doctrine of Method "Book II" | 1,171 blocks (81 notes) → 1,310 chunks |
| Kant, *Groundwork* (pg5682) | Labels all 181 blocks "PREFACE" | 181 blocks (18 notes) → 192 chunks |
| Hume, *Enquiry* (pg9662) | Selects nothing, and fails on footnote 9 (linked from a heading) | 290 blocks (34 notes) → 323 chunks; Selby-Bigge § 1–132 |

- **The current books stayed identical.** In every prototype, the seven current books came out byte-identical to today's output.
- **Totals:** 12 sources, 14 works, about 7,900 blocks and 8,900 chunks. Smith alone is about a quarter of the library.

### 2.5 What `philosophy_query.py` needs from the data
| Node | Relies on |
|---|---|
| classify, retrieve_author | Each book's `author` must equal a name in `Author` (lines 27-28) byte for byte; otherwise the filtered search finds nothing |
| retrieve_node | A library balanced enough that 8 unfiltered results reach the right author |
| grade_documents | A unique `passage_id` per passage, and self-contained text |
| decide_to_generate | At least 3 relevant passages, counted across all authors |
| generate → `ask.answer_from_documents` | `author`, `work`, `locator` and `passage_id` present; `chapter`/`section` whole numbers or absent; unique passage IDs (`build_verification_index` raises on duplicates); verbatim `page_content` (quotes are checked against it); labels short and plain enough to copy |
| modernize | The answer text only |

The new books' author strings are "Adam Smith", "Mary Wollstonecraft", "Immanuel Kant" (twice) and "David Hume". Translators are contributors, not creators.

---

## 3. Design decisions
- **D1. Three generations, each measured.** G1 adds the five books with the current books byte-identical. G2 fixes the current books' text. G3 embeds headings with the text. Each gets its own namespace and quiz comparison.
- **D2. New rules are switched on per profile.** Shared code is used only for markup none of the current books has: `div.pre`, `span.mnum`, and the new `division` label.
  - Hobbes's PART headings are real divisions, so PART handling is per profile.
  - Plain `<pre>` exists in *Leviathan* and *Subjection*, so `<pre>` handling is per profile too.
- **D3. One text-extraction rule from now on.** Add no extra space at inline tags, only at line breaks and block boundaries.
  - It applies to the new profiles in G1, and to the current ones in G2.
  - It applies to heading matching (`parsers.py:189`) as well as body text. For the current books this was checked to change nothing.
  - The only token changes allowed are rejoined words.
- **D4. Labels.**
  - **`division`.** A new top label, printed first. It holds Kant's divisions and Hume's Sections.
  - **Whole numbers.** `chapter` and `section` are whole numbers or absent.
  - **Copyable locators.** No em-dashes, Æ or trailing full stops in locators. Long titles go into unprinted metadata (`chapter_title`, `division_title`, `subheading`).
  - **Unknown headings stop the parse.** In new profiles, an unrecognised heading inside the selected text stops the parse.
  - **Paragraph numbering differs by profile. Document this in the README.**
    - Current profiles count paragraphs through a whole chapter, across § changes ("Chapter 19, §233, paragraph 30").
    - New profiles restart the count whenever the printed label path changes ("Section IV, Part I, §23, paragraph 2").
    - Both are unique. Both are marked "(edition-specific)".
- **D5. Text that keeps its lines is typed "table".**
  - Any `div.pre` or `<pre>` whose lines are kept becomes a block with content_type "table". That includes Leviathan's chart in G2, which is typed "prose" today (`parsers.py:275-277`).
  - Dedent it, strip trailing spaces and drop the outer blank lines. This tidies the text but doesn't make it rebuildable. The chunker strips whitespace at chunk edges, so 7 of Smith's tables still can't be rebuilt character for character.
  - What makes the rebuild test pass is its exemption for `content_type == "table"` (§5.4). Integrity already rejects tables as card material without raising an error: they fail its EL-type and EL-rebuild eligibility checks (`integrity/builder/eligibility.py:221-226`).
  - The type is also how the edition knows never to send a table to the model (§9.5).
- **D6. Work titles are decided once, before any quiz card is written for that book.**
  - Shorten Wollstonecraft to "A Vindication of the Rights of Woman". The " / With Strictures…" subtitle is what a model would drop.
  - Keep the other new titles as published.
  - Implement it as an override table keyed by Gutenberg ID, beside `BURKE_WORKS`.
- **D7. Only the author's words carry the author's name.** Exclude editor and translator material, as is already done for Burke (`BURKE_EDITORIAL_NOTES`, `parsers.py:29`).
- **D8. Voices the author doesn't hold are a known limitation.** Examples:
  - Kant's Antinomy theses and antitheses;
  - the Epicurus speech in Hume's Section XI;
  - Wollstonecraft's long quotations of Rousseau, Gregory and Fordyce.

  Mitigations:
  - labels where the text allows (A.3);
  - integrity exclusions, so quiz cards never treat these as the author's view (§5.6).

  ask.py can't be told the content type of a passage, because its prompt and schema are frozen.
- **D9. The modern edition lives outside Pinecone and the manifest.**
  - Translations are keyed by block ID plus a hash of the original text.
  - Modern text never becomes the `page_content` of anything passed to `ask.answer_from_documents`.
- **D10. `retrieval.py` and `ask.py` stay unchanged through G1–G3.** `retrieval.py` is shared with the quiz path, so changes there are optional later items (§10).

---

## 4. Phase 0: protect and prepare (no library change)
1. **Branch and tag.**
   - Create a branch (`git switch -c corpus-upgrade`) and tag the starting point (`git tag pre-corpus-upgrade`).
   - Merge the branch to `main` before the G1 activation commit, and make that commit on `main` (§5.9). Otherwise switching branches would silently switch the namespace.
2. **Back up what git doesn't track:**
   - the 12 EPUBs;
   - `reports/`;
   - `raw.jsonl` and `grades.jsonl` for all four quiz runs (065212, 070028, 070826, 172125). MANUAL §6.4 regrades 070826.

   Why the EPUBs matter: block IDs embed each EPUB's internal file names. A re-download from Gutenberg would change the namespace, and it could also orphan every quiz card and edition record.
3. **Record the index.** Write down every namespace and its vector count, from the Pinecone console or a read-only `describe_index_stats`.
4. **Make a golden hash file.** Commit a small file, for example `tests/golden/corpus_hashes.json`, mapping each `passage_id` to a short hash of its text and a short hash of its metadata.
   - The metadata hash leaves out `corpus_version` and, from G3 on, the embedded-text hash key.
   - A test compares the current offline preparation against this file.
   - It is regenerated deliberately at the end of each generation (§5.5, §6, §7).
5. **Retire or rewrite the stale test** (`tests/test_epub_pipeline.py:360-379`) and fix `reports/run_live_checks.py`.
   - From now on, tests never import `philosophy_query.py`, because its import builds a Tavily client (line 29).
   - A test that needs the file reads it as text.
6. **Add guards to `ingest.py`.** It isn't part of the manifest, so these change no namespace.
   1. `validate_records` rejects a `chapter` or `section` that isn't a whole number. Reject `bool` too.
   2. Preparation fails if a work has no question. Use verify's two-key lookup, work_id then source_id (`ingest.py:205`); otherwise single-work books would be rejected.
   3. `--upload` refuses `config.DEFAULT_NAMESPACE` and the active `AGORA_NAMESPACE`.
      - Update `tests/test_epub_pipeline.py:238-265`, which uploads the real corpus to a fake index under today's live name. Inside that test, patch the namespace names that `ingest.py` imported, not `config`'s own attributes.
      - Add a test that the guard refuses both namespaces.
   4. Reports:
      - write a default preparation report only with `--upload`, named after the namespace;
      - add a suffix for partial `--source` selections;
      - never silently overwrite a preparation or verification report. If the file is absent, write it. If it is present with identical content, accept it, so a rerun can resume an upload. Refuse on any difference;
      - point `test_offline_cli_without_credentials` (`:271-289`) at a temporary folder.
7. **Fix the docs.**
   - README: the example at line 33, the scope paragraph, the namespace rule, and lines 67-68.
   - MANUAL §6.1: the compare order.
8. **Acceptance:**
   - the suite is green;
   - offline preparation still prints `epub-v1-04b8672ea20df6c7`;
   - the backups, golden file and guard tests are in place.

---

## 5. Generation 1: add the five books (current books unchanged)

### 5.1 Shared parser changes
1. **Register the profiles.** Add the five profiles (`smith`, `wollstonecraft`, `critique`, `groundwork`, `hume`) to the whitelist (`parsers.py:131`) and to `PROFILES` (`:19`).
2. **Add the `division` label slot**, printed first.
3. **Handle `div.pre`.** Each `div.pre` becomes one block of type "table", following D5. Fail if it contains markup.
4. **New-profile-only rules:** D3 extraction, D4 numbering, and stop-on-unknown-heading.
5. **Title overrides** (D6).
6. **Bump `PARSER_VERSION`.**

The three prototypes used three different extraction rules, and the Smith/Wollstonecraft one applied none. Build the shared pieces once, then re-run every Appendix A assertion on the merged code. D3 changes only about six boilerplate paragraphs per book in pg3300 and pg3420.

### 5.2 Per-book profiles
Appendix A specifies each profile in plain language, including sample locators, `QUESTIONS` entries, regression assertions and integrity notes.

### 5.3 `ingest.py`
- **Entries:** five `WORKS` entries, each with `"works": 1`, and five `QUESTIONS` entries (Appendix A).
- **Embedding-input module.** Move the function that builds the embedded string into a small module of its own, and add that module's sha256 to the manifest, as `parsers.py` and `chunking.py` are today.
  - In G1 the module returns `page_content` unchanged.
  - From then on, any change to what gets embedded produces a new namespace automatically, which closes gap 1.

### 5.4 Tests
- **Source counts.** `tests/test_epub_pipeline.py:179`: 12 sources / 14 works.
- **New-book assertions:** the regression assertions from Appendix A.
- **Golden test:** the seven current books' records match the golden file.
- **Real-corpus counts.** `integrity/tests/test_builder_real_corpus.py:45` (`== 3401`) and any other real-corpus counts move to the new totals, updated on purpose.
- **Rebuild test.** `integrity/tests/test_builder_real_corpus.py:38` (rebuild every paragraph exactly) exempts `content_type == "table"` (D5). The eligibility filter already marks tables ineligible without raising an error (`integrity/builder/eligibility.py:221-226`).
- **Activation check.** A standalone script, not part of the default test run. It reads `philosophy_query.py` with `ast` and lists corpus authors missing from `Author`. It advises; it doesn't block (§5.9).

### 5.5 Offline acceptance (all free)
1. **Per-book review.** For each new book, run `ingest.py --source <file> --report <scratch path>`, then read the exclusions and about 15 locators against the EPUB. Three of these books parse "cleanly" today and are still wrong.
2. **Full preparation:** 12 sources, 14 works, about 8,900 chunks. Note the namespace.
3. **Golden test passes:** the current books are unchanged.
4. **Structural checks:**
   - all chapter and section values are integers;
   - body locators are unique within each work;
   - every note resolves;
   - no chunk exceeds 2,000 characters.
5. **Integrity checks:** `.venv/bin/python -m integrity sheet check` reports 32 ok, and the rebuild test passes (tables exempt).
6. **Suite green.**
7. **Regenerate the golden file** for all 12 books and commit it.
8. **Freeze the G1 parser code here.** A parser fix after this point means restarting at §5.5, which gives a new namespace. It also means discarding and rebuilding *all* new-book card drafts. Nothing can tell which drafts a parser change affected, because publishing checks quotes only, not block IDs (`integrity/builder/card_validation.py:22-31`).

### 5.6 Quiz cards for the new books, before activation
Cards are built from the offline corpus. That needs no upload and no Pinecone, although `build` does make paid calls to the drafting and attribution models.
1. **Survey the new books, then add exclusions to `integrity/integrity.toml`** for voices the author doesn't hold (D8):
   - Hume's Section XI speech;
   - Kant's Antinomy theses and antitheses, and the Paralogisms;
   - Wollstonecraft's long quotations of Rousseau, Gregory and Fordyce.

   Prefer `locator_regex` entries. If the Antinomy's locators carry THESIS and ANTITHESIS (A.3), one regex covers them. `block_id` entries are accepted (`integrity/common/settings.py:70-74`), but `integrity/tests/test_builder_real_corpus.py:64` calls `re.search` on `locator_regex` and would raise on such entries. If you use them, update that test first.
2. **Build per book:** `.venv/bin/python -m integrity corpus --source <file>`, then `build --source <file> --count N --false-premise 1`.
   - Use `--count 6` for Smith, Wollstonecraft and Hume.
   - Use `--count 6` for the Critique and `--count 2` for the Groundwork. `--source` builds use automatic per-work strata and ignore configured ones (`integrity/builder/build.py:184`), so these counts are what weight Kant's two books.
   - Keep `--false-premise 1` (`integrity/cli.py:168`); without it, each build adds 6 trick cards.
3. **Review every batch.** `integrity review` handles one batch per run, newest first (`integrity/builder/review.py:85-102` and `:248-268`). Repeat it until it reports no pending batch.
4. **Re-run the full suite,** because the toml changed after §5.5.
5. **Don't publish yet.** Publishing happens in §5.8, after the probes and the v001 comparison, so a late parser fix can't leave a published sheet behind.

### 5.7 Upload and verify
1. Run `ingest.py --upload --namespace <G1>`. It's about 2 million tokens, and a rerun resumes.
2. Then run `--verify --namespace <G1>`.

### 5.8 Compare before switching
- **Probe set.** Run 10–20 fixed questions through `retrieval.get_vectorstore(<old>)` and `get_vectorstore(<G1>)`. This costs only the query embeddings.
  - **Filtered probes** (Hobbes, Locke, Burke, Mill) must return the same passage IDs. A near-tie at 8th place may swap.
  - **Unfiltered probes** on the overlap topics show the crowding:
    - knowledge: Locke, Hume and Kant;
    - morality: Mill and Kant;
    - women: Mill and Wollstonecraft;
    - property: Locke and Smith.
- **Crowding cost on the old cards:**
  1. Run `.venv/bin/python -m integrity quiz --sheet v001 --namespace <G1>`.
  2. Then run `.venv/bin/python -m integrity compare r-20261121-172125 <that run>`.
  3. Expect a corpus_version warning (text matching). It's harmless here, because the old text is identical.
  4. A drop beyond "within noise" is the price of crowding. Accept it, or bring G3 forward.
- **Publish, then take the new books' baseline.**
  1. Run `integrity publish --note "add five books"` once. Check that the "added: N" it prints equals the number of cards you approved. This is sheet v002.
  2. Run `integrity sheet check`, and expect every card to be "ok".
  3. Then run `integrity quiz --sheet v002 --namespace <G1>`.

  After activation this run is also the v002 baseline. The namespace, sheet and grader are the same, and activation doesn't touch the quiz path.
- **Your own runs.** Try `philosophy_query.py` with `AGORA_NAMESPACE=<G1>`. Without R1, Kant, Hume and Wollstonecraft still take the "other thinkers" route.

### 5.9 Activate (one commit on `main`, by you)
1. Merge the branch to `main`.
2. Run the activation check script.
3. Commit:
   - `config.py:11` set to `<G1>`;
   - and, if you authorize it, R1 (§8).

   If you decline R1, activation still works. Those three authors stay on the "other thinkers" route (unfiltered search plus web), and their books are used less.
4. Restart running processes, because both settings are read at import.
5. Smoke tests:
   - one question per new author through `philosophy_query.py`;
   - one `ask.py --question`.

### 5.10 Rollback
Revert the activation commit, or set `AGORA_NAMESPACE=epub-v1-04b8672ea20df6c7`. The old namespace is never modified.

---

## 6. Generation 2: fix the current books' text
**Scope:** one parser change and one namespace, measured on sheet v002. Details are in Appendix B.

| Fix | What changes | Integrity follow-up |
|---|---|---|
| B1: Essay section detection | pg10615: +11 blocks, −1; 149 locators renumbered | Card `c-b102241c55` moves from paragraph 78 to 84. Its stored locator goes stale. That doesn't affect grading, because label checks compare against the retrieved items (`integrity/quiz/grading/mechanical.py:91-104`). Refresh it after G3 (§7.1) |
| B2: exclude Army Estimates paragraphs 1, 38, 40, 42, 43 | pg15679: −5 blocks; 39 locators renumbered | Change the stratum `["3-37",39,41]` to `["2-36",37,38]` **in the same commit**. Applied to the old numbering, the new stratum would include Fox |
| B3: D3 extraction for the current profiles | 6 books, 317 blocks (Leviathan unchanged) | 5 cards' text changes; their skeletons match, so `sheet check` passes |
| B4: include the three dedications | pg10615 +3, pg3207 +5, pg34901 +1 | Optionally add "EPISTLE DEDICATORY" to the `locke-front-matter` stratum |
| B5: bare FINIS ends the text; ": " stripped from Mill's notes; Leviathan's chart keeps its lines and becomes a "table" block (D5) | pg3207, pg27083 | The chart leaves the card pool, which is correct. No card uses it |

**Acceptance**
- The golden test shows exactly these changes and no others, including the chart's new type. Any change in the five new books fails it.
- `sheet check` passes, and the rebuild test passes (tables exempt).
- Run `integrity quiz --sheet v002 --namespace <G2>`, then `compare <v002 baseline run> <G2 run>`.
- Regenerate the golden file.
- Activate by changing `config.py` only.

---

## 7. Generation 3: embed headings with the text
**What changes**
- Change the embedding-input module (§5.3):
  - chunks of 200+ characters are embedded as "Author | Work | division/book/part | chapter title | heading | section title", a blank line, then the text;
  - shorter chunks are embedded as they are (the prefix made tiny chunks rank higher).
- The module's hash changes, so the namespace changes automatically.
- `text` stays equal to `page_content`. langchain-pinecone returns the stored `text` as `page_content`, so the prefix never reaches citations or quotes.

**Checks**
- Store a hash of each embedded string in its record's metadata, and have `--verify` check it.
- Add a test that stored text equals `page_content`.
- The golden test passes, ignoring the new hash key.

**Cost:** about 13% more tokens.

**Measure, then activate:** run `integrity quiz --sheet v002 --namespace <G3>`, then `compare <G2 run> <G3 run>`. Activate by changing `config.py` only.

### 7.1 After G3: refresh the cards (R7)
`sheet check --apply` only re-anchors cards whose text changed or moved (`integrity/builder/maintain.py:151-153`). It doesn't refresh corpus_version, work or locator on cards that are "ok".
- **Extend `--apply`** to refresh those fields as well. This is an integrity-module change.
- **Re-anchor** card `c-b102241c55`.
- **New sheet and baseline.** Sheets are write-once, so this publishes v003. Record a new baseline on v003; it's a paid quiz run. Every later use of R7 likewise means a new sheet and a new baseline. That's why it waits until after G3.

---

## 8. `philosophy_query.py`: changes that need your authorization
None of these has been made. Line numbers are as of commit `1f527ab`. R1 may add a line and shift the rest, so each item also names its function.

### Required for goal 1
**R1: `Author`, lines 27-28.** Add `"Immanuel Kant"`, `"David Hume"` and `"Mary Wollstonecraft"`, spelled exactly like that; they match the books' metadata.
- **Timing:** make it in the activation commit (§5.9).
  - Earlier, their questions find nothing.
  - Later, they keep taking the "other thinkers" route.
- **Effect:** their questions search only their own books, comparisons fetch both sides from the books, and web search becomes a fallback.
- **Trade-off:** the books cover only part of each author. Hume's *Enquiry* has no politics, and Kant's two books have none of his political writings. Some questions will get "the passages don't address this" where today they get a web answer. O1 addresses that.

### Optional: independent; none required
- **O1: `decide_to_generate`, line 257.** Require one or two relevant passages per named author before skipping the web, instead of 3 in total.
- **O2: `rewrite_question`'s prompt, lines 314-318.** Fix the "YRewrite" typo, and add non-political vocabulary (impressions and ideas, a priori, duty, the division of labour).
- **O3: `Author`, line 28.** Drop "Sam Harris" until his book is indexed. This is marginal either way:
  - today his questions get an empty search, then a rewrite, then the web;
  - without him they'd take the "other thinkers" route.
- **O4: `sys_message_input`, line 58.** The unused translation prompt ends with a sentence that belongs to the gate prompt. The change is cosmetic.
- **O5: the `__main__` block, line 447.** Print failed citation checks, so a failure doesn't look like a pass.
- **O6: `modernize`, lines 334-366.** Once the edition (§9) exists, use its checked renderings as a reference.
- **O7: `grade_documents`, lines 228-230.** Show the grader each passage's author and work.

None of these affects the quiz, which calls `ask.answer_question` and never the graph (`integrity` sets the namespace before importing ask). None affects integrity, and none needs a re-embed.

---

## 9. The modern-English edition

### 9.1 What it is
- **The pieces:** a new module, `edition.py`, translates every block of every work into modern English. An `editions/` folder holds the translations, and a reader shows the original and modern text side by side.
- **Isolation:**
  - it reads the library offline through the parser;
  - it never touches Pinecone or `ask.py`;
  - `philosophy_query.py` needs no change.

### 9.2 Unit and key
- **One record per parser block** (a paragraph or a note).
  - Every chunk is an exact substring of its block.
  - A chunk's `passage_id` is its `block_id` plus `:cN`, so any cited chunk can find its translation.
- **The key:** block ID, the sha256 of the original text, and the edition ID.
  - Block IDs survive profile and selection changes; this was tested.
  - They don't survive a change in how the parser walks a file. The text hash catches that.
- **`edition check`** compares the store with a fresh parse. Each record is:
  - **valid:** same ID, same hash;
  - **stale:** same ID, new hash. Retranslate it;
  - **moved:** the hash is found exactly once elsewhere. Re-key it;
  - **orphan:** none of the above.

### 9.3 Storage and versioning
- **The store holds translations only:**
  - block ID and source hash;
  - modern text and notes;
  - checks, judge verdict, usage and status.

  Reading order and labels always come from the live parse at read time, so they can't go stale.
- **Files:**
  - `editions/modern/<edition_id>/edition.json` records the prompt and its hash, the model and parameters, the schema version, and the corpus version and source hashes it was built from;
  - one append-only `<work>.jsonl` per work. The file name is the work ID with ":" replaced by "__", for Windows checkouts.
- **Versioning.** The edition ID is a hash of prompt, addendum, model, parameters and schema. Any change starts a new folder, and `config.py` names the active one. `config.py` isn't in the manifest, so this never changes a namespace.
- **Git:**
  - commit released editions only;
  - keep drafts in an ignored folder, and back them up, since they cost money.

### 9.4 Commands
| Command | What it does |
|---|---|
| `plan` | Dry run that prints the token and cost estimate |
| `pilot` | Translates one chapter per author |
| `build --work --limit --max-usd` | Resumable full run. It skips finished records, and `--max-usd` is cumulative across resumed runs through a spend ledger |
| `check` | Runs the code checks in §9.7 |
| `judge` | Runs the sampled judge in §9.7 |
| `read` | The reader |

**Cost cap**
- Refuse any call whose worst case exceeds the remaining budget.
- Stop at once on a 401 or 403.
- Retry a 429 or 5xx a bounded number of times.

**Packing.** Short consecutive paragraphs of one chapter share a call, up to about 8,000 characters. Long paragraphs go whole, never split. The response schema is a list of `{block_id, modern_text, notes}`, which replaces d5c5845's single-passage `ModernizedWork`. Each input block must come back exactly once.

### 9.5 Hard content
- **Tables** (Smith 10, Critique 7, Locke 1, Leviathan's chart): kept verbatim and never sent to the model. They are identified by content_type "table" (D5).
- **Verse:** keep the lines; give a prose gloss in the notes, labelled as the edition's.
- **Latin, Greek and French:** keep the original and add "[Translation: …]". Keep terms of art such as *a priori* and *ens realissimum*.
- **Notes:** translated separately and attached to their owner block.
- **Labels:** keep "Sect. 27.", Hume's § numbers, and Kant's THESIS/ANTITHESIS/PROOF.
- **Emphasis in capitals** (Wollstonecraft): render it as emphasis.
- **Short paragraphs** (under 200 characters): send the previous paragraph as read-only context.

### 9.6 Prompt
- Copy the "Translate Prose" prompt (`sys_message_input` in `philosophy_query.py`). Leave out its last sentence, which belongs to the gate.
- Put the rules for tables, verse, foreign text and notes in a separate, separately hashed addendum.
- **Drift check.** It finds `sys_message_input` with `ast`, without importing the file. A difference is a warning, not a failure, so your own edits never break the build.

### 9.7 Faithfulness
**Code checks on every record:**
- the length ratio is within a calibrated band, starting at 0.7–1.8;
- every number is kept;
- capitalised names are kept, with an alias list for modernised spellings;
- negations are not reduced;
- quotation marks and section labels are kept;
- there is no meta text ("Here is…").

**Sampled judge**
- A model from a different family from the translator reviews:
  - about 3% of each work, and at least 10 records per work;
  - every flagged record;
  - every verse, foreign-language and note record.
- It rules on omissions, additions, meaning, certainty and negation, quoting spans that code then checks.
- Release only if the sample has no negation flips. You settle disagreements.

**Model choice is yours.** Suggestion: translate with the model `modernize` already uses (`gpt-6.2-sol`), so the edition and in-answer renderings read alike, and judge with Claude Sonnet 5.5.

### 9.8 Size and cost
| | Characters | Input tokens | Output tokens (assumed ×1.15) |
|---|---|---|---|
| Current 7 books | 4.05M | 1.01M | 1.17M |
| New 5 books | 4.50M | 1.13M | 1.29M |
| **Total** | **8.56M** | **2.14M** | **2.46M** (cap 2.78M) |

- **Prompt overhead:** add about 0.8M prompt tokens with packing, or 2.5M without.
- **Characters are an upper bound.** They are counted between the Gutenberg START/END markers.
- **Cost formula:** input tokens × input price + output tokens × output price, at the chosen model's current prices.
- **Pilot first.** The pilot measures the real ratio and the cost per 1,000 characters before the full run.

### 9.9 Reader
- **CLI first:** `edition.py read --work pg7370:main --chapter 5` shows two columns. `rich` is already a dependency.
- **Streamlit later** (roadmap step 5):
  - pick an author, work and division;
  - original beside modern, with notes in expanders and a deep link per paragraph;
  - chat citations link to their paragraph by stripping `:cN` from `passage_id`.
- **Ordering.**
  - The parser emits notes after all body text, so the reader places notes by owner block.
  - Headings aren't blocks, so the reader shows them from label changes.

### 9.10 When
- **Pilot after G1, on new-book chapters,** whose text is final at G1.
- **Full build after G2.** Before then, B3 would make about 317 translations stale.

### 9.11 Later
- **Searching the modern renderings.** Only in a separate namespace, whose hits map back to the original chunks and are merged in `retrieval.py`.
  - Never use shared passage IDs: they would crash `build_verification_index`, and quotes could verify against words the author never wrote.
  - Not before G3 is measured. The quiz already finds 22 of 23 paragraphs.
- **`modernize` using stored renderings:** O6.

---

## 10. Later and optional improvements
| Item | Where | Note |
|---|---|---|
| Keep only the best chunk per paragraph | `retrieval.py`, behind a flag | Lowest-risk diversity fix. It changes the quiz path, so measure it |
| Sentence-aware chunk boundaries | `chunking.py` (custom splitter) | LangChain's sentence separators break the rebuild test (`integrity/tests/test_builder_real_corpus.py:38`). The custom splitter passed it |
| Shorter Essay title; shorter Hobbes locators (137 are over 120 characters) | `parsers.py` | Cards must be updated. Low priority: the baseline had only 1 label mismatch |
| Embedding reuse by text hash; a guarded delete-namespace command; a stronger verify relevance check | `ingest.py` | Reuse saves cents. The delete command must refuse the active, default and baseline namespaces |
| `tools.py` fixes | `tools.py` | Before roadmap step 4 |

---

## 11. What could be damaged, and how it's protected
| Asset | Risk | Protection |
|---|---|---|
| Live namespace | Overwritten by an upload that computes the same name | The embedding-input module is hashed into the manifest (§5.3); uploads to the default or active namespace are refused (§4 step 6) |
| Old namespaces | Deleted too early | Keep them until the next generation is active and re-baselined. Delete only with the guarded command, `epub-v1-99c8507c0ba5ab33` first |
| `philosophy_query.py` | Unwanted edits | Untouched; R1 and O1–O7 happen only with your OK |
| `ask.py` and the quiz | A changed prompt, schema or `page_content` | `ask.py` untouched; edition text never becomes `page_content`; `retrieval.py` untouched through G1–G3 |
| `integrity_data` and `integrity.toml` | Stale cards, misplaced strata, a half-filled sheet | `sheet check` before each upload. B2's stratum change in the same commit. New cards only after the parser is frozen. Every batch reviewed, and one publish whose count matches the approved cards. Sheets are write-once |
| Quiz conclusions | Misread comparisons | Same sheet and grader; explicit `--sheet` and `--namespace`; older run first in `compare` |
| Reports, EPUBs, run files | Overwritten, or not in git | No-overwrite reports; Phase 0 backups |
| Tests | Regressions hidden | A golden hash file regenerated per generation; counts changed on purpose; the stale test retired; the guard test added |
| Branches | Namespace switches silently | The activation commit lands on `main` |
| Costs | Runaway spending | Embeddings cost a few cents per generation; the edition is piloted, with a cumulative cap |
| Secrets | Leaked by tests or tools | Tests never import `philosophy_query.py`; nothing prints the environment |

---

## 12. Acceptance checklist
**Phase 0**
- [x] Backups made.
- [x] Golden file committed.
- [x] Stale test retired and `run_live_checks.py` fixed.
- [x] Guards and guard tests added.
- [x] README and MANUAL §6.1 fixed.
- [x] Suite green.
- [x] Offline preparation still prints the live namespace.

**G1 offline**
- [x] Each new book reviewed by hand.
- [x] Preparation gives 12 sources / 14 works.
- [x] Golden test green.
- [x] Integer, unique-locator, note and size checks pass.
- [x] `sheet check` reports 32 ok.
- [x] Rebuild test passes, with tables exempt.
- [x] Suite green.
- [x] Golden file regenerated.

**G1 cards**
- [x] Parser frozen.
- [x] Survey done; exclusions added.
- [x] Cards built per book: 6 each, except the Groundwork at 2, all with `--false-premise 1`.
- [x] Every batch reviewed.
- [x] Suite re-run.

**G1 online**
- [x] Upload done.
- [x] Verify passes.
- [x] Filtered probes unchanged.
- [x] v001 crowding compared against `r-20261121-172125`.
- [x] v002 published once, with "added" equal to the number of approved cards.
- [x] `sheet check` after publishing: every card ok.
- [x] v002 baseline recorded.
- [ ] Merged to `main`.
- [ ] Activation check run.
- [ ] Activation commit made (config, plus R1 if authorized).
- [ ] Smoke tests pass.

**G2**
- [x] Only the intended differences appear.
- [x] B2's stratum change is in the same commit.
- [x] Compared on v002.
- [x] Golden file regenerated.
- [ ] Activated.

**G3**
- [x] Embedded-text hash verified.
- [x] Compared on v002.
- [ ] Activated.
- [ ] R7 refresh done.
- [ ] v003 baseline recorded.

**Edition**
- [ ] Pilot reviewed.
- [ ] Full build within the cap.
- [ ] Every flag resolved.
- [ ] Judge sample shows no negation flips.
- [ ] Released edition committed.
- [x] CLI reader works.

**Cleanup**
- [ ] Old namespaces deleted with the guarded command, only after soak.

---

## 13. Review record

### Round 1: adversarial review of revision 1 (19 findings)
| # | Severity | Finding | Resolution |
|---|---|---|---|
| 1 | BLOCKER | Aligned table text breaks integrity's rebuild test (7 Smith tables differ, 3 uncertain; also Leviathan's chart in B5) | D5: dedent and strip tables; the rebuild test exempts tables (§5.4); rebuild check added to §5.5 and §6 |
| 2 | MAJOR | The upload guard breaks `tests/test_epub_pipeline.py:238-265` | §4 step 6.iii: patch constants in that test; add a guard test |
| 3 | MAJOR | Namespace-named reports would be overwritten by partial runs and by the offline CLI test | §4 step 6.iv: default report only with `--upload`, suffix for partial selections, no overwrite, test writes to a temp folder |
| 4 | MAJOR | The `compare` argument order was reversed (the plan and MANUAL §6.1) | §0, §5.8, §6, §7 use `compare <older> <newer>`; MANUAL fix in §4 step 7 |
| 5 | MAJOR | The activation check in the suite would stay red until R1 | §5.4: a standalone advisory script; §5.9 says what happens if R1 is declined |
| 6 | MAJOR | G2/G3 "on v002" was impossible if cards were re-anchored (write-once sheets; `quiz` defaults to the latest sheet) | Explicit `--sheet v002`; re-anchor deferred to §7.1 (R7 → v003 → new baseline) |
| 7 | MAJOR | The golden-test lifecycle contradicted itself | §4 step 4: committed hash file, regenerated per generation, ignoring corpus_version and the G3 hash key |
| 8 | MAJOR | New-book cards came too late to measure G1 | §5.6: cards built offline before the upload; v002 baseline taken before activation (§5.8) |
| 9 | MAJOR | No survey, exclusions or strata for the new authors | §5.6 step 1; D8 |
| 10 | MINOR | Default false-premise cards, and publishing once per book | `--false-premise 1`; a single publish |
| 11 | MINOR | B2 can't be keyed by block ID; the stratum change must land with the parser change | Appendix B2 matches text prefixes; same-commit rule in §6 |
| 12 | MINOR | Edition: packing vs schema, table contradiction, brittle drift test, ":" in file names, stale order and labels, per-run cap, git bloat | §9.3–9.6 revised; A.3 no longer says to translate tables |
| 13 | MINOR | The `embedding_input` bump relied on memory | §5.3: embedding-input module hashed into the manifest |
| 14 | MINOR | Paragraph numbering differs between old and new profiles | D4 documents it |
| 15 | MINOR | Backups missed three runs; the EPUB rationale was incomplete | §4 step 2 |
| 16 | MINOR | README and `run_live_checks.py` staleness | §2.1, §4 steps 5 and 7 |
| 17 | NIT | Prototypes used different extraction rules | §5.1: re-run all assertions on the merged code |
| 18 | NIT | Line 45, not 44; the two-key `QUESTIONS` lookup | §5.4; §4 step 6.ii |
| 19 | NIT | When to merge the branch | §4 step 1; §5.9 |

### Round 2: validation of revision 2
**Verdict:** nothing puts the live namespace, EPUBs, git, reports or integrity data at risk.

**Original findings:**
- 16 resolved.
- #1, #9 and #10 only partly resolved; the new findings below complete them.

**Confirmed against the code:**
- Integrity rejects tables without raising an error.
- `corpus` and `build` don't use Pinecone.
- A v002 baseline taken before activation stays valid after it.
- Deferring R7 keeps the G2 and G3 comparisons valid: grading never uses the card's anchor locator.

**New findings:**

| # | Severity | Finding | Resolution (revision 3) |
|---|---|---|---|
| N1 | BLOCKER | Leviathan's chart is typed "prose", so the table exemption doesn't cover it and G2's rebuild test still fails. Dedenting alone doesn't fix Smith's tables either | D5: any text that keeps its lines is typed "table"; B5 row; golden-test note in §6 |
| N2 | MAJOR | "Review once" handles one batch of five, so v002 would hold one book's cards | §5.6 step 3: repeat `review` until no batch is pending. §5.8: publish once and check "added" |
| N3 | MINOR | `--source` builds ignore configured strata, so Kant strata in the toml would do nothing | §5.6 step 2: per-book counts (Critique 6, Groundwork 2) |
| N4 | MINOR | `block_id` exclusions crash `test_builder_real_corpus.py:64`, and the suite ran before the toml edit | §5.6 step 1: prefer `locator_regex`. §5.6 step 4: re-run the suite |
| N5 | MINOR | The no-overwrite report rule blocks a resumed upload | §4 step 6.iv: accept identical content, refuse only on a difference |
| N6 | MINOR | Publishing v002 before upload and probes risks a stranded sheet if the parser changes | §5.5 step 8: freeze the parser. Publishing moved to §5.8 |

Smaller corrections:
- the upload-guard test patches the names `ingest.py` imported (§4 step 6.iii);
- the `mechanical.py` reference is now lines 91-104.

### Round 3: targeted check of revision 3
**Verdict:** all 9 items (N1–N6, and the partial #1, #9, #10) are resolved, and each fix's factual claim matches the code.

**Confirmed against the code:**
- **Rebuild check:** integrity's rebuild-test logic, run over all 12 books in both the G1 and the G2 state, found 0 failures and 0 uncertain rebuilds outside the exempt tables: Smith 10, Critique 7, Leviathan's chart 1, pg7370 1.
- **Publish count:** `publish` prints "added: N" (`integrity/builder/handlers_sheet.py:34`).
- **Build counts:** `--count` passes straight through with `--source` (`integrity/builder/handlers.py:88-104`).
- **Report rule:** the preparation report is deterministic (`tests/test_epub_pipeline.py:224-227`), so the "accept identical content" rule works.

**One NIT, now fixed:** after a post-freeze parser fix, discard and rebuild all new-book drafts, and run `sheet check` right after publishing (§5.5 step 8, §5.8).

---

## Appendix A: new-book profiles
Locators end in ", paragraph N (edition-specific)" unless shown in full.

### A.1 Smith: *An Inquiry into the Nature and Causes of the Wealth of Nations* (pg3300, profile `smith`)
**Structure**
- **h2 headings:** "INTRODUCTION AND PLAN OF THE WORK.", 5 "BOOK N." and 32 "CHAPTER N. TITLE".
- **22 h3 headings inside chapters:**
  - 16 PART headings in mixed styles;
  - "Conclusion of the Digression…";
  - "Conclusion of the Chapter.";
  - Book II's "INTRODUCTION.";
  - "APPENDIX TO BOOK IV";
  - "CONCLUSION." (Book V ch. 1);
  - "APPENDIX TO ARTICLES I. AND II.—…".
- **Other markup:** 10 `div.pre` tables, and 69 inline `{…}` notes (mostly references).

**Rules**
- **Selection:** starts at the Introduction heading and stays on to the end. The title, byline and contents are excluded.
- **BOOK h2:** sets "Book N", clears chapter and heading, and keeps selection on. That keeps Book IV's opening paragraphs.
- **CHAPTER h2:** sets an integer chapter and the chapter title, and clears the heading.
- **PART h3**, in any punctuation style: sets heading "Part N". It is allowed only inside a chapter; elsewhere it stops the parse. It never sets `part`, which prints before the chapter and belongs to Hobbes.
- **Fixed headings:**
  - Book II's "INTRODUCTION." sets heading "Introduction" and clears the chapter.
  - "APPENDIX TO BOOK IV" sets heading "Appendix" and clears the chapter.
  - "Conclusion of the Chapter." and "CONCLUSION." replace the Part label.
- **No change:** "Conclusion of the Digression…" and "APPENDIX TO ARTICLES…". The Articles that follow belong to Part II again.
- **Stays as prose:** the centred italic sub-headings and the ARTICLE labels. `{…}` notes stay inside their paragraphs.
- **Any other heading** stops the parse.

**Sample locators**
- "Introduction and Plan of the Work, paragraph 1"
- "Book I, Chapter 2, paragraph 2"
- "Book I, Chapter 10, Part II, paragraph 14"
- "Book II, Introduction, paragraph 1"
- "Book IV, paragraph 1"
- "Book IV, Chapter 2, paragraph 9"
- "Book V, Chapter 1, Part III, paragraph 114"

**QUESTIONS:** `"pg3300": "How does the division of labour increase the productive powers of labour?"`

**Assertions**
1. "The annual labour of every nation is the fund" is at Introduction and Plan of the Work, paragraph 1. "In that rude state of society" is at Book II, Introduction, paragraph 1. "Political economy, considered as a branch" is at Book IV, paragraph 1.
2. The chapters are exactly Book I 1–11, II 1–5, III 1–4, IV 1–9 and V 1–3. Book V ch. 1 has Parts I–IV and Conclusion.
3. No document has `part`, and no locator matches `Part [IVX]+, Chapter`.
4. There are exactly 10 tables. Chapters are integers and locators are unique.

**Integrity:** no exclusions found yet. The survey (§5.6) should check long quotations.

**Your call:** "{this was the current designation for steam engines}" (Book I ch. 1, paragraph 8) is an editor's gloss. Remove it or leave it.

**Translation:** tables stay verbatim. Archaic spellings to expect: "shew", "recompence".

### A.2 Wollstonecraft: *A Vindication of the Rights of Woman* (pg3420, profile `wollstonecraft`)
**Structure**
- **Front matter:**
  - a producer credit;
  - the title;
  - the contents, with h4 "INTRODUCTION." and 13 h5 "CHAPTER N. TITLE" entries;
  - the editor's biography (h4 "A BRIEF SKETCH…", 13 paragraphs).
- **Dedication:** h4 "TO", h5 address lines, 20 paragraphs, then "M. W.".
- **Introduction and half-title:** h4 "INTRODUCTION." (17 paragraphs), then an h4 half-title.
- **Chapters:** 13, each an h4 "CHAPTER N." followed by an h5 title. h5 "SECTION 5.1–5.5" and "SECTION 13.1–13.6" divide Chapters 5 and 13.
- **Notes and marks:**
  - 22 note paragraphs starting "(*Footnote." (one is "(Footnote.");
  - 21 "*" marks in the body text;
  - 8 ">From";
  - 2 asterisk rows.

**Rules**
- **Selection** starts at h4 "TO". Everything before it is excluded, including the biography.
- **"TO"** sets heading "Dedication". Its address lines and "M. W." are excluded.
- **"INTRODUCTION."** sets heading "Introduction". The half-title is excluded.
- **Chapters:** only an h4 "CHAPTER N." sets a chapter (integer). The h5 before the first paragraph becomes the chapter title.
- **h5 "SECTION C.S"** sets section S (integer) and restarts paragraph numbers. It stops the parse if C isn't the current chapter.
- **Notes:** a paragraph starting "(*Footnote." or "(Footnote." becomes a note owned by the paragraph before it. Strip the wrapper. Notes don't advance paragraph numbers.
- **Cleanup:**
  - remove "*" marks from body text, because quotes across them would fail verification;
  - exclude asterisk rows;
  - change ">From" to "From".
- **Any other heading** stops the parse.

**Sample locators**
- "Dedication, paragraph 2"
- "Introduction, paragraph 1"
- "Chapter 5, §1, paragraph 1"
- "Chapter 13, §6, paragraph 10"
- Note: "Note block 118 to Chapter 5, §4, paragraph 3 (edition-specific)"

**QUESTIONS:** `"pg3420": "Why does Wollstonecraft argue that women should be educated as rational beings rather than to please men?"`

**Assertions**
1. No text contains "M. Wollstonecraft was born in 1759", "memoir written by her afflicted husband" or "2001".
2. "Having read with great pleasure a pamphlet" is at Dedication, paragraph 2. "After considering the historic page" is at Introduction, paragraph 1. The chapters are 1–13.
3. The (chapter, section) pairs are exactly (5, 1–5) and (13, 1–6), all integers.
4. There are 22 notes, none starting "(" or "Footnote", each owned by a prose block. No text contains "*" or ">From".

**Integrity:** exclude her long quotations of Rousseau, Gregory and Fordyce (D8).

**Check by hand:** the one unmarked note is attached to Chapter 7, paragraph 36 by rule. It may belong to the paragraph before.

**Translation:** render capitals as emphasis. Spellings to expect: "connexion", "subtile".

### A.3 Kant: *The Critique of Pure Reason* (pg4280, profile `critique`)
**Structure**
- **Front matter:** title page and contents.
- **h2 headings:** Preface 1781, Preface 1787, Introduction (with h3 I–VII), "I. TRANSCENDENTAL DOCTRINE OF ELEMENTS." and "II. Transcendental Doctrine of Method".
- **102 h3 headings for everything else:** Parts, Divisions, two book styles, chapters, sections, § headings and two APPENDIX headings.
- **§ numbering:**
  - §1–10 in the Aesthetic, then §1–23 again in the Analytic;
  - §7, §8, §19 and §21 are centred paragraphs, not headings.
- **Other markup:**
  - 7 `<pre>` tables;
  - 52 run-in labels ("THESIS.", "PROOF.");
  - 81 notes;
  - note-number links "[N]" in the text;
  - small capitals split names ("B ACON").

**Rules**
- **Selection** starts at the first Preface. Title page and contents are excluded.
- **Divisions.** Each `division` heading clears book, chapter, sub-label and §:
  - "Preface to the First Edition" and "Preface to the Second Edition";
  - "Introduction";
  - "Transcendental Aesthetic" and "Transcendental Logic";
  - "Transcendental Analytic" and "Transcendental Dialectic";
  - "Doctrine of Method".

  The Doctrine of Elements heading only clears.
- **Book headings:** both styles set "Book I" or "Book II".
- **Chapter headings** set an integer chapter.
- **Sub-labels go in `heading`:**
  - "Section N";
  - "Introduction";
  - "Appendix", which also clears book and chapter.

  Numbered h3s become:
  - "Section I" in the main Introduction;
  - "Introduction, Section I" in the sub-introductions;
  - "Section IX, Solution III" in the Antinomy.

  The title-only h3 clears the sub-label.
- **§ numbers.** "§ N" at the start or end of a heading, or in a centred paragraph, sets an integer `section`. It replaces a "Section N" sub-label in the locator.
- **Run-ins** are joined to the start of the next paragraph. A run-in is a centred paragraph, or an all-caps paragraph of 12 words or fewer that isn't verse or a letter. If a heading comes in between, the run-in is dropped (1 case).
- **Recommended, not yet prototyped:** in the Antinomy, carry THESIS or ANTITHESIS into the printed sub-label, so every paragraph shows which side it argues (D8). Re-check locator uniqueness.
- **Cleanup:**
  - remove the note-number links (`#linknote-*`, `#linknoteref-*`);
  - `<pre>` becomes a table (D5).
- **Translator notes.** Exclude Meiklejohn's notes through an exclusion set like `BURKE_EDITORIAL_NOTES`:
  - [29] and [30] are his;
  - [33] and [70] probably are;
  - check [31].

**Sample locators**
- "Preface to the First Edition, paragraph 1"
- "Introduction, Section VI, paragraph 10"
- "Transcendental Aesthetic, §2, paragraph 1"
- "Transcendental Analytic, Book I, Chapter 2, §12, paragraph 3"
- "Transcendental Dialectic, Book II, Chapter 2, Section IX, Solution III, paragraph 22"
- "Doctrine of Method, Chapter 1, Section I, paragraph 26"

**QUESTIONS:** `"pg4280": "How are synthetical judgements a priori possible?"`

**Assertions**
1. Preface A has 17 blocks and Preface B 26. The Introduction has Sections I–VII.
2. No Doctrine of Method block has `book`. Its chapters are {1, 2, 3, 4}.
3. § values are Aesthetic {1..10} and Analytic {1..23}, all integers.
4. Every note has an owner, and no text matches `\[\d+\]`.
5. The first antinomy's thesis starts "FIRST CONFLICT…THESIS.". No block is exactly "PROOF." or "ANTITHESIS.".

**Integrity:** exclude the Antinomy's theses and antitheses and the Paralogisms (D8). Weight Kant's two books by their per-book card counts (§5.6).

**Title:** keep it, or drop the leading "The". Decide before cards (D6).

**Translation**
- The English is 19th-century but technical: "conception" = Begriff, cognition, intuition.
- There are about 95 Latin terms.
- Tables stay verbatim (§9.5).

**Quoting:** 598 "à priori" and 1,345 em-dashes, and `ask.normalize` folds neither. Watch the self-check results in §5.8's runs.

### A.4 Kant: *Fundamental Principles of the Metaphysic of Morals* (pg5682, profile `groundwork`)
**Structure**
- **Front matter:** title page and contents (13 `p.toc`).
- **h2 headings:** PREFACE, and the FIRST, SECOND and THIRD SECTION headings.
- **Subheadings:** 9 h2s, 3 in the Second Section and 5 plus "CONCLUDING REMARK" in the Third.
- **End marker:** h3 "THE END".
- **Notes:** 18 `<pre>` blocks starting "* ", each after a paragraph holding one bare "*".

**Rules**
- **Selection:** from "PREFACE" to "THE END".
- **Divisions:** `division` is "Preface", "First Section", "Second Section" or "Third Section".
- **Other h2s** go into `subheading` (metadata only). Paragraph numbers continue through them.
- **Notes:** a `<pre>` starting "*" becomes a note owned by the paragraph above. Remove its "*", and remove the bare "*" marks from body text.
- **No chapter or section values.**

**Sample locators**
- "Preface, paragraph 11"
- "Second Section, paragraph 53"
- Note: "Note block 71 to First Section, paragraph 15 (edition-specific)"

**QUESTIONS:** `"pg5682": "What is the categorical imperative?"`

**Assertions**
1. Blocks per division are 17/21/90/35. No locator starts "PREFACE".
2. There are 18 notes, each owned by the block above it. No leading or bare "*" remains.
3. No contents or "THE END" text remains. The last body block is in the Third Section, under "CONCLUDING REMARK".

**Title:** keep Abbott's title; "Groundwork" would misname this translation.

**Translation:** this book needs the least work.

### A.5 Hume: *An Enquiry Concerning Human Understanding* (pg9662, profile `hume`)
**Structure**
- **Front matter:** "Extracted from:" and the contents.
- **Sections:** 12 h2 "SECTION N" headings, each followed by an h3 title. The first uses an Arabic numeral, and II, VI and X have no full stop.
- **Parts:** 13 h4 PART headings. Sections IV, V, VII, VIII and X have Parts I–II; XII has Parts I–III.
- **Selby-Bigge numbers:** 132 of them (`span.mnumtag > span.mnum > a#mnumN`), each first in its paragraph.
- **Footnotes:** an h2 FOOTNOTES with 34 `blockquote.footnote`, each starting "Footnote N: (return)".
- **Index:** an h2 INDEX (Selby-Bigge's).
- **A heading reference:** footnote 9 is linked from the h3 "OF PROBABILITY".

**Rules**
- **Selection** starts at the first SECTION.
- **SECTION** sets `division` "Section I" to "Section XII" (Roman numerals), and clears part, § and title.
- **h3** sets `division_title`, which is metadata only.
- **h4 PART** sets `part` "Part N". Selection stays on.
- **Selby-Bigge numbers** set an integer `section` and are stripped from the text. The number carries over to the unnumbered paragraphs that follow, until the next one.
  - Here `section` is the Selby-Bigge §, not Hume's "Section IV".
- **FOOTNOTES** keeps selection on. Strip the "Footnote N:" labels.
- **INDEX** stops selection, excluding 1,425 blocks.
- **Footnote 9:** a note reference on a heading is handed to the next body paragraph (§46, paragraph 1).

**Sample locators**
- "Section I, §1, paragraph 1"
- "Section IV, Part I, §23, paragraph 2"
- "Section X, Part II, §99, paragraph 2"
- Note: "Note footnote9 to Section VI, §46, paragraph 1 (edition-specific)"

**QUESTIONS:** `"pg9662": "Is our belief in cause and effect founded on reasoning or on custom?"`

**Assertions**
1. § values are exactly 1..132, all integers. No body text starts with "N. ".
2. Footnote 9's owner is §46, paragraph 1.
3. 1,425 index blocks are excluded, and no text contains "Extracted from".
4. There are 34 notes, none starting "Footnote". Parts appear only in Sections IV, V, VII, VIII, X and XII; XII alone has a Part III.

**Integrity:** exclude the Epicurus speech in Section XI (D8).

**Optional:** footnote 17 has source mojibake: "VelleÃ¯ty" should be "Velleïty".

**Translation**
- About 119 archaic spellings ("encrease", "connexion").
- Long periodic sentences.
- Latin quotations and three "[Greek: …]" placeholders.

---

## Appendix B: current-book fixes (G2)
Each fix was switched on alone in a prototype. Every book it doesn't target stayed byte-identical.

**B1. Essay section detection (pg10615)**
- **New rules:**
  - a paragraph "N. …" whose N isn't greater than the current section is body text;
  - a paragraph of 200 or more characters starting "N." is body text that also starts section N;
  - a bare "24." is a section heading.
- **Result:** 9 dropped paragraphs return, along with two enumerated items. The wrong § labels are corrected, for example ch. 21's §1/§2 → §59.

**B2. Army Estimates (pg15679)**
- Exclude paragraphs 1 (editor), 38 (Fox), 40 (Sheridan), 42 (reporter's N.B.) and 43 (Pitt).
- Match them by the start of their text, as the prototype's `BURKE_OTHER_SPEAKERS` did. Don't use `BURKE_EDITORIAL_NOTES`, which matches HTML `id` attributes (`parsers.py:285-286`), and don't use block IDs, which come from positions.
- Change the stratum in the same commit.

**B3. D3 extraction for the current profiles**
- 317 blocks in 6 books.
- The only token changes are the 88 rejoined words, plus 54 "800,000 l." becoming "800,000l.".

**B4. Dedications**
- Locke's Epistle Dedicatory (pg10615).
- Hobbes's dedication to Godolphin (pg3207).
- Mill's dedication (pg34901).

**B5. Small cleanups**
- A bare "FINIS" ends the text (pg3207).
- Strip ": " from 3 notes (pg27083).
- Leviathan's ch. 9 chart keeps its lines (D5).

**Not now**
- **Leviathan's 9 `<p>` margin notes as headings.** This would renumber 7 chapters, including ch. 27 with its 2 cards.
- **Retyping Locke's Hooker notes.** ask.py never shows the type.
- **Dropping the 73 reference-only notes under 80 characters.** Your call, because it conflicts with the "include author notes" policy.

---

## Appendix C: evidence
All files are under `/private/tmp/claude-501/-Users-marscheung-SideProjects-agora/631d962c-adc6-47f6-a9b7-13dc1ae03165/scratchpad/agents/`. They are temporary, so copy anything you want to keep.

| Folder | Contents |
|---|---|
| `pipeline-review/` | `prep.json`, `stats.json`, `variants.json`, `proxy.json`, `proxy2.json` |
| `existing-books/` | `proto/parsers.py` (fixes switched on by `PROTO_FIXES`), `diff_fix.py`, `out/` |
| `smith-wollstonecraft/` | `proto/parsers.py`, `parsers_smith_wollstonecraft.diff`, `scripts/regression_checks.py`, `out/` |
| `kant-hume/` | `proto/parsers.py`, `parsers_kant_hume.diff`, `out/proof_run.txt` |
| `consumer-translation/` | `size_table.txt`, `block_id_stability.py`, `packing_sim.py` |
| `adversary/` | `rebuild_new.py`, `ws_check.py`, `diff189.py`, `card_impact.py`, `deny_strata.py` |

The prototypes are evidence, not code to copy. They were built separately and are not merged.


## 14. Execution review amendments (2026-11-24)

- Three independent explorer agents reviewed corpus extraction, integrity and the edition. Their findings were fixed and rechecked offline.
- G4 is an additional isolated source repair after the frozen G1/G2/G3 checkpoints. It excludes Kant translator note `linknote-28` and preserves nine Wollstonecraft verse paragraphs plus one verse note. Exactly 11 passage records differ from G2/G3; `tests/golden/g4_deltas.json` declares them. Measure G4 on unchanged v002 after G3, then perform R7 once and baseline v003. This preserves the three original generation comparisons.
- “Each new book reviewed by hand” above records Codex source/markup inspection, not an independent human endorsement. Quiz batches were likewise reviewed by Codex, with eight targeted wording edits and one rejected tentative Groundwork false-premise card. The approved count was 30.
- The filtered probe exception was a swap at eighth place for one Mill question: top seven unchanged, with scores approximately 0.5400 versus 0.5396. This is the near-tie exception permitted in §5.8.
- Edition review accepts exact source/render hashes only and cannot replace the required independent judge sample. `retranslate` and `rejudge` target explicit block IDs, clear obsolete decisions, append history and use the same spend ledger. Tables never go to either model. Paid mutations refuse released paths, including symlinked paths.
- The partial edition remains unreleased because content flags and judge disagreements require resolution. The retained $10 cap also prevents treating a partial edition as a full-build acceptance.
- Do not resume the interrupted v002 run as a clean baseline: it contains saved quota-error records that normal resume skips. Start a fresh explicit v002/G1 run once credits are restored, retaining the interrupted receipt.
- No namespaces were deleted. The original live namespace is unchanged. Additional superseded G1 staging evidence is retained for audit; cleanup requires the exact-target safeguards and a later successful activation/baseline.
- Resume attempt `r-20261125-022259` (2026-11-24 local time) reached the configured Anthropic answer model for 42 cards, then saved 20 HTTP 400 insufficient-credit errors. Grading was explicitly interrupted after 25 cards to avoid further charges on an unusable baseline; there is no completed scorecard. Restore **Anthropic** credits and start a fresh G1/v002 run, retaining both interrupted receipts. A normal `--resume` would skip the saved error rows.
- G2 and G3 staging proceeded independently of activation, in isolated worktrees with all 12 EPUB hashes verified and preparation reports equal to their frozen receipts. Both full uploads passed record-by-record text/metadata verification and retrieval checks for all 14 works. Their measurement comparisons and activations remain gated by a valid G1/v002 baseline.
- The saved edition pilot's 69 missing current judge receipts were completed under the existing cumulative cap. The resulting check has 92 valid renderings, zero missing judge receipts, 58 unresolved review cases, and `release_ready: false`. No disagreement has been accepted as human-reviewed.

- Corrected G4 completed its upload and exact verification of 8,936 records and retrieval checks for all 14 works. All four generations are now staged; none was newly activated during this resume. The active namespace remains `epub-v1-04b8672ea20df6c7`.
- Following a user-reported Anthropic top-up, attempt `r-20261125-024904` still received insufficient-credit errors and was interrupted before grading (zero successful answers, 56 saved error rows). A separate minimal request confirmed the same HTTP 400 response. The effective key comes from the project's `.env`, with no ambient key override, and requests use `api.anthropic.com`. Confirm that the funded Console organization owns this key before another paid baseline attempt. Diagnostic receipt: `reports/anthropic-credit-recheck-20261125-025058.json`.
- The quiz runner now aborts immediately on explicit provider credit exhaustion, retaining completed answers and the failed-call receipt without retrying, asking later cards, or grading. Resuming a saved credit-error row also aborts with instructions to start fresh; temporary rate limits still retry. No answer, retrieval, judge prompt, sheet, corpus fingerprint, or grader version was changed (`g-eaa3d7`). Validation: 35 focused tests, 633 full-suite tests, changed-file Ruff, and `git diff --check` passed.

- The user confirmed the funded Console organization owns the configured API key and shows a positive balance. A further minimal request at `2026-11-25T02:55:06Z` still failed with HTTP 400 insufficient credit (request `req_011ChNtiy9dCxVaPDtgpxUWH`). No key override or alternate endpoint was found. Resolve this provider billing/access rejection before another baseline attempt; first require a successful minimal probe. A secret-free support packet is saved at `reports/anthropic-credit-support-20261124.json`.

- Fresh v002 runs completed the answer stage: G1 `r-20261125-025823`, G2 `r-20261125-025955`, G3 `r-20261125-030003`, G4 `r-20261125-030012`. All 248 raw answers have no answer-call errors. All four scorecards are UNTRUSTED because the configured OpenAI judge exhausted credits; do not treat their judged comparisons as acceptance evidence. Canonical copies of all runs and their raw files are retained in `integrity_data/runs/`; the independent data roots are also preserved. Restore OpenAI credits and use `integrity regrade <source run>` to obtain fresh trusted scorecards without rerunning Anthropic. Set `INTEGRITY_MODELS__TRACING=off` for those runs because LangSmith also reached its monthly trace quota.
- R7 preview validated all 62 cards against final G4 without publishing. Seven edition code-flag false positives were resolved by explicit source/rendering Codex review after independent faithful judgments; 51 cases remain unresolved, no paid calls were added, and the edition remains partial and unreleased.
- An activation rehearsal exposed one fake-upload test that relied on the prepared namespace being inactive. The test now supplies explicit protected namespace names, preserving the production upload guard after G4 activation. The focused activation-environment checks passed (18 tests).

- The configured OpenAI `gpt-4.1` judge was rechecked directly at `2026-11-25T06:07:38Z`; it still returned HTTP 429 `insufficient_quota` / `credit_balance_exhausted` (`reports/openai-judge-credit-check-20261125-060740.json`). The model client now remembers explicit credit failure for its lifetime, skips application retries, and makes no later model requests; ordinary temporary rate limits retain retries. This changes failure handling only; grader `g-eaa3d7` is unchanged.
- Pytest discovery is now restricted to `tests` and `integrity/tests`, so recoverable copies of tests inside backups are preserved without being collected as duplicate test modules.

- On 2026-11-25, a minimal OpenAI `gpt-4.1` check succeeded and grading resumed from all four saved source runs, with `INTEGRITY_MODELS__TRACING=off`. All source raw-file hashes were verified before regrading. The prior untrusted runs remain preserved; no Anthropic answers are repeated.
- Fresh cloud checks reconfirmed all staged namespace counts and exact G4 round trips for 8,936 records, plus retrieval checks for 14 works (`reports/pre-activation-staging-verification-20261125.json`).
- Four edition drafts received source-bound wording corrections. Three now pass fresh independent judgments; the Smith paragraph remains flagged after three refinement rounds and is retained for review. The cumulative ledger is $1.600150, with 48 unresolved records and no release. Exact revision receipts and the current review packet are saved in `reports/`.

- All four regrades completed with TRUSTED health: G1 `r-20261125-185253`, G2 `r-20261125-185300`, G3 `r-20261125-185309`, G4 `r-20261125-185316`. Each passed 24/24 required controls and had zero judge-call errors. Raw answers remain byte-identical to their saved source runs. All receipts are now also in canonical `integrity_data/runs/` directories.
- Trusted main metrics (Found; Complete; Faithful; fully passing) are G1: 45/49; 104/116; 590/616; 16/58. G2: 45/49; 105/116; 599/627; 14/58. G3: 48/49; 112/116; 632/653; 18/58. G4: 48/49; 105.5/116; 603/631; 15/58. G4's lower answer-level scores relative to G3 are retained and investigated, not hidden: all six completeness-loss cases received the same passage set, five with identical assembled initial context; the remaining case changed passage order. The report's noise bands do not model answer-generation variance. Full comparisons, context hashes, failures, and separate holdout results are preserved.
- Execution-order amendment: all four generations were measured while the original corpus remained active. The prepared deployment is one final corrected G4 + R1 activation commit on `main`, with all intermediate namespaces and measurements retained. The exact two-file patch is `reports/final-G4-R1-activation-20261125.patch`. No application source has been changed yet.
- The first staging graph smoke case failed at `classify` with OpenAI HTTP 429 `credit_balance_exhausted`, after all regrades had completed. The SDK and application use the same key, organization, project, and official endpoint. Zero smoke cases completed, so activation remains pending. Restore OpenAI credits for smoke tests and the final v003 baseline; the trusted regrades do not need repeating.

- User-authorized local activation: changed `config.py` to final G4 and added exactly Immanuel Kant, David Hume, and Mary Wollstonecraft to the query graph's `Author` Literal. Default/effective namespace, retained author labels, syntax, and four focused offline tests passed. No paid calls were made. This supersedes the earlier activation-pending notes for local file changes; live application verification, commit/merge, and any process restart remain separate. Paid integrity grading is stopped pending new explicit authorization.

- User-authorized one-question application smoke: Kant good-will question passed all ten flow assertions against final G4, with eight relevant Kant passages, five verified citations, and no rewrite, web fallback, or citation retry. Recorded 11 chat-model calls and 11,857 chat tokens (query embedding usage excluded). The display echoed `<responseAnswer>` wrapper tags; this cosmetic issue is retained as an observation, with no application edits or extra model calls. Receipt: `reports/kant-application-smoke-20261125-210950.json`. Stop after this question; other smoke cases and bulk integrity grading remain unrun.

- Upload/app-switch phase finalized at user request: `40a26d7` was fast-forward merged into local `main`; full offline suite passed 637 tests in 60.77s. Existing namespaces and draft editions were retained. No additional paid API calls, remote push, or application process restart were performed. Later edition work, deferred R7/v003 evaluation, and the cosmetic display-tag observation do not reopen the completed upload/app-switch phase.
