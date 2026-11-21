# integrity: how accurate is Agora?

A separate module that builds quiz answer sheets from the corpus and grades `ask.answer_question` against
them. It never changes the main program. Full design: `INTEGRITY_MODULE_PLAN.md` (section 17 lists what was
built differently from the original plan).

Run everything from the repo root: `.venv/bin/python -m integrity <command>` (written `integrity` below).

## Two parts, run independently

**Part A: answer sheets.** Needs the EPUBs plus `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` (drafting and the
speaker double-check). Does not need Pinecone or Agora.

```sh
integrity corpus                      # paragraphs per author/work, what is eligible and why others are not
integrity build --dry-run --seed 1    # preview the sampling plan, no model calls
integrity build --seed 1              # draft 24 passage cards + 6 false-premise cards; bad drafts are binned
integrity review                      # YOU approve / edit / reject each card (resumable)
integrity publish --note "first sheet"    # writes integrity_data/sheets/sheet-v001.json (read-only)
```

**Part B: the quiz.** Needs a published answer sheet (it refuses to run without one, exit 2), Agora's usual
keys, and a judge key (`OPENAI_API_KEY`).

```sh
integrity quiz                        # ask every question, grade, print the report card, save the files
integrity quiz --limit 5              # cheap trial
integrity quiz --mechanical-only      # code-only checks, no judge model
integrity report latest               # reprint the last report card
integrity compare NEW OLD             # did my change help? differences inside the noise are marked
integrity calibrate --n 5             # spot-check 5 judge decisions (about 10 minutes)
integrity regrade RUN_ID              # grade saved answers again with the current grader (no Agora calls)
```

Other commands: `retire CARD_ID --reason ...`, `sheet list`, `sheet show [VERSION]`, `sheet check [--apply]`.

## Reading a report card

Read **Found, Complete and Faithful together**, never one alone. An Agora that answers from memory without
retrieving can look fine on Complete. If the grader health line says UNTRUSTED or UNVERIFIED, do not trust the
judged numbers (Complete and Faithful); the code-checked ones (Found and citation checks) are still exact.
`failures.md` in the run folder shows, for each failed card, what Agora retrieved, what it said, and which
check failed. Holdout ("sealed") cards are in every run but their details are hidden there.

## Runbooks

- **After changing Agora:** `integrity quiz`, then `integrity compare latest <baseline run>`. Keep or revert.
- **After adding a book to the main program:** `integrity corpus --source NEW.epub`,
  `integrity build --source NEW.epub --count 6`, `review`, `publish`, then `quiz` for a new baseline.
- **After changing the parser or chunker:** `integrity sheet check`, then `sheet check --apply`, retire any
  missing or ambiguous cards, `publish`, then `quiz` for a new baseline.
- **After changing the judge model or prompts:** `integrity regrade <baseline run>` so old and new runs share a grader.

## Where things live

- `integrity/` code, `integrity/integrity.toml` settings (models, check limits, strata weights, denylist).
- `integrity_data/sheets/` published sheets (commit these), `drafts/` batches in progress, `runs/` report cards.
  `runs/*/raw.jsonl` and `grades.jsonl` are git-ignored.
- Settings overrides: CLI flags, `INTEGRITY_<SECTION>__<KEY>` environment variables, or a TOML file named by
  `INTEGRITY_CONFIG`. `models.tracing = "off"` stops LangSmith tracing of prompts and answers.

## Exit codes

0 ok, 1 usage error or nothing to do, 2 no valid answer sheet, 3 Agora entrypoint missing or its result breaks
the contract (see plan section 4.2), 4 configuration or credentials, 5 run failed, 6 grader untrusted (`--strict`),
130 interrupted (a run can be resumed with `--resume RUN_ID`).

## Tests

```sh
.venv/bin/python -m pytest integrity/tests -q     # offline: no network, no model calls
.venv/bin/ruff check integrity
```

Never run bare `pytest` (the repo's flat module layout needs `python -m pytest`).
