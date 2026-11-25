# Integrity Tool: User Manual

This tool measures how accurately Agora answers questions about its books, and how often it makes things up.
Use it every time you change Agora, so you know whether each change made Agora better or worse.

---

## 1. What the tool does

The tool has two parts. Each one runs on its own.

| Part | What it does | How often you run it |
|---|---|---|
| **Part A: Answer sheets** | Builds a quiz from the books. A model drafts quiz cards from random paragraphs, code checks every quote, and you approve the cards. Approved cards are published as an answer sheet. | When you first set up, when you add books, and when you want more cards |
| **Part B: Quiz** | Asks Agora every question on the answer sheet, grades the answers, and prints a report card. | Every time you change Agora |

**Key words**

- **Card**: one quiz question. Each card holds the question, 2 or 3 key points a good answer must contain, and an exact quote from the book proving each point.
- **Answer sheet**: a published, numbered set of approved cards (v001, v002, ...). A published sheet is never changed. To add or remove cards, you publish a new version.
- **Run**: one quiz against one answer sheet.
- **Report card (scorecard)**: the results of one run.
- **Sealed cards (holdout)**: about 15% of cards. They are asked in every quiz, but their details are hidden in the failure report. If Agora improves on normal cards but not on sealed ones, you may be tuning Agora to the quiz rather than improving it.

---

## 2. One-time setup

### 2.1 Work from the project folder

Every command in this manual is run from the project folder:

```sh
cd /Users/marscheung/SideProjects/agora
```

### 2.2 Optional: a shortcut

The full command is long. To type `integrity` instead, add this line to your `~/.zshrc`, then open a new terminal:

```sh
alias integrity="/Users/marscheung/SideProjects/agora/.venv/bin/python -m integrity"
```

This manual always shows the full form, `.venv/bin/python -m integrity ...`. With the shortcut you can replace that with `integrity ...`.

### 2.3 API keys

The tool reads keys from the project's `.env` file. You need:

| Key | Used by |
|---|---|
| `OPENAI_API_KEY` | Part A (drafting cards) and Part B (the grader), plus Agora's search |
| `ANTHROPIC_API_KEY` | Part A (checking who is speaking in each card) and Agora's answers |
| `PINECONE_API_KEY` | Agora's search (Part B only) |

The build and quiz commands call these paid services. The `--dry-run`, `corpus`, `review`, `publish`, `sheet`, `report` and `compare` commands do not.

### 2.4 Check that it works

```sh
.venv/bin/python -m integrity --help
```

You should see a list of commands: corpus, build, review, publish, retire, sheet, quiz, report, compare, regrade, calibrate.

---

## 3. Part A: Building an answer sheet

The cycle is: look at the books, preview the plan, build the drafts, review them, publish.

### Step A1: See what material is available (optional, free)

```sh
.venv/bin/python -m integrity corpus
```

**What happens:** the tool reads every book and counts how many paragraphs are usable as quiz material. Footnotes, Latin, lists, fragments, and passages where the author quotes an opponent are excluded, and each excluded paragraph gets a reason.

To see examples of excluded paragraphs, for example ones rejected for being too short:

```sh
.venv/bin/python -m integrity corpus --excluded EL-len --show 5
```

### Step A2: Preview which paragraphs would be picked (free)

```sh
.venv/bin/python -m integrity build --dry-run --seed 1
```

**What happens:** code picks paragraphs at random, spread evenly across authors and across each book. Nothing is sent to any model and nothing is saved. The seed number makes the pick repeatable: the same seed with the same books always gives the same paragraphs.

### Step A3: Build the cards

Start small the first time:

```sh
.venv/bin/python -m integrity build --seed 1 --count 3 --false-premise 0
```

Then the full build, which drafts 24 normal cards plus 6 trick cards by default:

```sh
.venv/bin/python -m integrity build --seed 2
```

**What happens, for each paragraph:**

1. A model (OpenAI) drafts a question, 2 or 3 key points, and an exact quote for each key point.
2. Code checks every quote letter by letter against the book. A draft that fails any check is thrown away, and another paragraph from the same part of the book is tried, up to 3 times.
3. A second model (Anthropic) checks that each key point is really the author's own view, not someone the author is quoting or arguing against.

**What you see at the end:**

```
filled 30/30 slots; unfilled: -
discarded 4: HC4=3, HC5=1
flags: attribution_cue=2
batch written to integrity_data/drafts/b-20261121-...
```

- **filled**: cards made.
- **discarded**: drafts thrown away, with the reason codes (see section 8.4).
- **flags**: notes that will appear on cards during review.

**Trick cards (false premise):** each one asks a question built on something false, for example "Why did Locke defend absolute monarchy?". A good Agora corrects the premise instead of inventing an answer. To change how many are made, use `--false-premise N`.

**Building from one author or one book:**

```sh
.venv/bin/python -m integrity build --author "Thomas Hobbes" --count 6 --false-premise 0
.venv/bin/python -m integrity build --source pg3207-images-3.epub --count 6
```

### Step A4: Review the cards (your job)

```sh
.venv/bin/python -m integrity review
```

**What happens:** the cards from the newest batch are shown one at a time. Each screen shows:

- the author, work and location in the book
- the paragraph, with the quotes highlighted, plus a little of the paragraphs before and after for context
- the question and the key points
- any flags (notes from the automatic checks)
- the speaker check result for each key point

**Keys:**

| Key | Action |
|---|---|
| `a` | Approve the card |
| `e` | Edit it (opens your text editor with the question, key points and quotes) |
| `r` | Reject it (you'll be asked for a reason) |
| `s` | Skip for now |
| `?` | Show the review checklist |
| `q` | Quit. Your progress is saved; run `review` again to continue |

**Review checklist: approve a card only if all of these are true**

1. **The question makes sense on its own.** Agora is asked the question with no paragraph in front of it. Reject or edit questions that say "in this passage", "in this paragraph", "the preacher", "the new scheme", or anything else that only makes sense next to the text.
2. **Each key point actually answers the question.** If the question is about A and a key point is about B, Agora will be marked down for a correct answer.
3. **Each key point says what the paragraph says, and no more.** Watch for:
   - hedges that get dropped ("perhaps", "seems to me")
   - softened claims made absolute ("less regret" written as "no regret")
   - "originated with" where the text only says "was done by"
4. **The author is speaking**, not someone they quote, argue against or mock. The speaker check helps, but you decide.
5. **The question is something a curious reader might really ask.**
6. **For trick cards:** the premise is really false according to the paragraph.

You do not need to have read the book. You only judge whether the card matches the paragraph in front of you.

When editing, keep quotes copied exactly from the paragraph: old spellings, odd punctuation, everything. An edited quote is checked again, and a card that fails the checks can't be approved.

To review an older batch:

```sh
.venv/bin/python -m integrity review --batch b-20261121-063131-s1
```

### Step A5: Publish

```sh
.venv/bin/python -m integrity publish --note "first sheet"
```

**What happens:** every approved card from every unpublished batch is collected into a new answer sheet, `integrity_data/sheets/sheet-vNNN.json`. Earlier cards carry over. The file is made read-only and stamped with a fingerprint, so any later edit to it is detected. About 15% of the new cards are marked sealed.

To check it:

```sh
.venv/bin/python -m integrity sheet list
.venv/bin/python -m integrity sheet show
```

### Removing a bad card from a published sheet

```sh
.venv/bin/python -m integrity retire c-45a72f1918 --reason "question says 'in this passage'"
.venv/bin/python -m integrity publish --note "retired a bad card"
```

The card disappears from the next version but stays in the older versions.

---

## 4. Part B: Running the quiz

### Step B1: Quick test (3 questions)

Do this first after any big change to Agora, so you find crashes cheaply.

```sh
.venv/bin/python -m integrity quiz --limit 3
```

### Step B2: Full quiz

```sh
.venv/bin/python -m integrity quiz
```

**What happens:**

1. **Pre-flight checks.** Is there a published answer sheet? Is Agora's `answer_question` function there? Are the keys set? Is the grader a different model family from Agora's, so it isn't grading its own homework? If any check fails, the quiz stops and says what to fix.
2. **Asking.** Each question is sent to Agora, and only the question. Everything Agora returns is saved straight away in `raw.jsonl`. You'll see one line per card:
   ```
   [12/32] c-5dfcfaa442 ok (9.8s)
   ```
3. **Grading.** This is the slow part, with many judge calls per answer. You'll see:
   ```
   [graded 12/32] c-5dfcfaa442 (14.2s)
   [controls 3/28] C2
   re-checking a sample of 86 judge items for consistency ...
   ```
   - **Round 1, code-only checks:** did Agora find the right paragraph? Are its quotes real? Did it invent passage IDs?
   - **Round 2, the judge:** a model answers small yes/no questions, and must copy exact words as proof. Code checks that proof. A "yes" without valid proof counts against Agora, never for it.
   - **Grader self-test (controls):** fake answers with known correct grades are slipped in. If the judge gets any wrong, its scores are labelled UNTRUSTED.
4. **Report card.** Printed in the terminal and saved in `integrity_data/runs/<run id>/`.

**Other useful options:**

```sh
.venv/bin/python -m integrity quiz --author "John Locke"     # only one author's cards
.venv/bin/python -m integrity quiz --cards c-5dfcfaa442,c-0f68ac47dd
.venv/bin/python -m integrity quiz --mechanical-only         # code checks only, no judge
.venv/bin/python -m integrity quiz --strict                  # exits with an error if the grader is not TRUSTED
```

### If a run is interrupted

The answers are saved as they arrive. To continue a run from where it stopped:

```sh
.venv/bin/python -m integrity quiz --resume r-20261121-070826
```

If the answers were all collected but grading was interrupted, grade the saved answers without asking Agora again:

```sh
.venv/bin/python -m integrity regrade r-20261121-070826
```

---

## 5. Reading the report card

```
HEADLINE (29 main cards)
  Found      right paragraph retrieved           22/23    96%
  Complete   key points covered                  54/58    93%
  Faithful   claims supported by citations       286/301  95%
  Fully passing cards                            8/29
  Errors 0 · Wrongful refusals 3 · Answers with no citations 1
...
GRADER HEALTH  controls 24/24 must-pass ✓ · ... · trust TRUSTED
```

### 5.1 The three headline numbers

Read them together, never one alone.

| Number | Question it answers | Checked by |
|---|---|---|
| **Found** | Did Agora pull up the paragraph the card came from? | Code (exact) |
| **Complete** | Did the answer say what a good answer must say (the key points)? | Judge |
| **Faithful** | Is every claim Agora made backed by the passage it cited? This is the main hallucination measure. | Judge |

- **Fully passing** is the strict all-in-one count: right paragraph found, every key point covered, every claim supported, citations present and correct, no wrongful refusal.
- **Why read them together:** an Agora that answers from memory can score well on Complete while scoring badly on Found and Faithful. A low Found with a high Complete is a warning sign.

### 5.2 The trust label

The grader health line ends with one of these:

| Label | Meaning | What to do |
|---|---|---|
| **TRUSTED** | The judge passed every self-test | Use all the numbers |
| **UNTRUSTED** | The judge failed at least one self-test | Use only the code-checked numbers (Found and the citation checks). Look at which control failed |
| **UNVERIFIED** | No self-tests ran | Treat judged numbers with caution |
| **NOT RUN** | You used `--mechanical-only` | Only code-checked numbers exist |

### 5.3 failures.md

The most useful file, in `integrity_data/runs/<run id>/failures.md`. For every card that did not fully pass, it shows:

- the question, and where the answer should have come from
- the passages Agora retrieved, in order
- Agora's answer
- which checks failed, with the judge's evidence

Before blaming Agora, check whether the card itself is at fault, for example a vague question.

### 5.4 Common failure codes

| Code | Meaning | Usually means |
|---|---|---|
| `M1 not_found` | The right paragraph wasn't retrieved | A search problem in Agora |
| `M6 trivial_quotes` | A citation quote is shorter than 6 words | Agora is quoting fragments |
| `M7 invalid_ids` | Agora cited a passage it never retrieved | An invented citation (serious) |
| `M8 label_mismatches` | A citation names the wrong author, work or location | A sloppy citation |
| `M9 no_citations` | The answer has no structured citations | Agora's quote checker had nothing to check |
| `M13 unmapped_inline_citations` | An inline citation matches nothing Agora retrieved | Possibly invented, or oddly formatted |
| `J1 absent` | A key point is missing from the answer | An incomplete answer |
| `J3 not_supported` | A claim isn't backed by its cited passage | **Hallucination** |
| `J3 contradicted` | The cited passage says the opposite | **Hallucination** (serious) |
| `J3 unverified` | The judge couldn't prove its verdict | Often grader noise; check by hand |
| `J4 refused` | Agora said it couldn't answer an answerable question | Usually a search miss |
| `J5 premise_not_corrected` | Agora went along with a trick question's false premise | **Hallucination** (serious) |

### 5.5 Check the grader yourself

```sh
.venv/bin/python -m integrity calibrate --n 5
```

**What happens:** five of the judge's decisions are shown with their evidence. You mark each one agree, disagree or unsure. Your agreement rate is printed on every later report card. Do this after your first quiz, and again whenever the judge's model or prompts change.

---

## 6. Routines

### 6.1 After every change to Agora (the main loop)

```sh
.venv/bin/python -m integrity quiz --limit 3          # 1. quick crash test
.venv/bin/python -m integrity quiz                    # 2. full run
.venv/bin/python -m integrity compare r-20261121-070826 latest   # 3. compare with your baseline run
```

Then:

1. **Read `compare`.** Differences marked "within noise" are wobble, not real change. One card out of thirty is about 3%.
2. **Read `failures.md`** for cards that newly fail.
3. **Keep the change if** Faithful and Found held or improved without hurting the others. Otherwise rethink or revert it.
4. **When you keep a change,** note the new run ID. It's your new baseline.

`compare` only compares runs on the same answer sheet and the same set of cards. Comparing a 3-card test run with a full run is refused unless you add `--force`, in which case only the shared cards are compared.

### 6.2 After adding a book to Agora

First add and upload the book using Agora's own workflow (see the main README). Then:

```sh
.venv/bin/python -m integrity corpus --source NEWBOOK.epub
.venv/bin/python -m integrity build --source NEWBOOK.epub --count 6
.venv/bin/python -m integrity review
.venv/bin/python -m integrity publish --note "added NEWBOOK"
.venv/bin/python -m integrity quiz                    # new baseline on the new sheet version
```

A new sheet version means new baseline numbers. Don't compare runs across sheet versions.

### 6.3 After changing how books are parsed or chunked

Passage IDs can shift when parsing changes. Check every card can still find its paragraph:

```sh
.venv/bin/python -m integrity sheet check
.venv/bin/python -m integrity sheet check --apply      # re-attach moved cards; publishes a new version
```

Cards reported as `missing` or `ambiguous` need retiring (see section 3, "Removing a bad card"). Then run a new baseline quiz.

### 6.4 After changing the judge's model or prompts

Re-grade your baseline with the new grader, so old and new runs are graded the same way:

```sh
.venv/bin/python -m integrity regrade r-20261121-070826
.venv/bin/python -m integrity calibrate --n 5
```

### 6.5 Growing the answer sheet over time

More cards give steadier numbers. Every so often:

```sh
.venv/bin/python -m integrity build --seed 3
.venv/bin/python -m integrity review
.venv/bin/python -m integrity publish --note "more cards"
```

Each build skips paragraphs already used, so you won't get duplicates.

---

## 7. Troubleshooting

| What you see | Cause | Fix |
|---|---|---|
| `invalid int value: '1:'` | A typo in the command (here a stray colon) | Retype the command without it |
| `the provider rejected the API key` (exit 4) | A key in `.env` is wrong or revoked | Create a new key with the provider, update `.env`, run again |
| `needs OPENAI_API_KEY, which is not set` | A missing key | Add it to `.env` |
| `no published answer sheet found` (quiz, exit 2) | Nothing published yet | Do Part A, steps A3 to A5 |
| `filled 6/30 slots` with many discards | The drafting model keeps failing a check | Look at the discard codes (section 8.4); tell Claude which codes dominate |
| `grading 32 answers ...` and nothing for a long time | Grading is slow, not stuck | Wait. Progress lines appear per card. If it's truly stuck, Ctrl-C, then `regrade <run id>` |
| `WARNING: judged metrics ... are UNTRUSTED` | The judge failed a self-test | Trust only Found and the citation checks for this run. Look at which control failed |
| `... .lock is held by process NNNN` (exit 4) | Another quiz or review is still running | Wait for it to finish. A lock left by a crashed process is cleared automatically on the next run |
| `review` shows cards you already handled | You ran a new build; review opens the newest batch | Use `--batch <id>` to pick a batch |

---

## 8. Reference

### 8.1 All commands

| Command | What it does | Calls paid models? |
|---|---|---|
| `corpus [--source FILE] [--excluded CODE --show N]` | Counts usable paragraphs | No |
| `build [--count N] [--false-premise M] [--seed S] [--author NAME] [--source FILE] [--dry-run]` | Drafts and checks cards | Yes (no with `--dry-run`) |
| `review [--batch ID]` | Approve, edit or reject cards | No (unless you edit, which re-checks quote uniqueness locally) |
| `publish [--note TEXT]` | Publishes a new answer sheet version | No |
| `retire CARD_ID --reason TEXT` | Removes a card from the next version | No |
| `sheet list` / `sheet show [VERSION]` | Lists or shows published sheets | No |
| `sheet check [--apply]` | Checks cards still match the books | No |
| `quiz [--limit N] [--author NAME] [--cards IDS] [--sheet VERSION] [--mechanical-only] [--resume RUN] [--strict]` | Runs the quiz | Yes |
| `report [RUN_ID or latest] [--format text,md,json]` | Shows a report card again | No |
| `compare RUN_A RUN_B [--force]` | Compares two runs | No |
| `regrade RUN_ID` | Re-grades saved answers without asking Agora | Yes (judge only) |
| `calibrate [RUN_ID] [--n 5]` | You spot-check the judge | No |

### 8.2 Exit codes

| Code | Meaning |
|---|---|
| 0 | OK |
| 1 | Usage error, or nothing to do |
| 2 | No valid answer sheet |
| 3 | Agora's `answer_question` is missing or returned something malformed |
| 4 | Configuration or API key problem |
| 5 | The run failed (for example, every question errored) |
| 6 | Grader not trusted (only with `--strict`) |
| 130 | Interrupted with Ctrl-C (resume with `--resume`) |

### 8.3 Where things are saved

| Path | Contents | Commit to git? |
|---|---|---|
| `integrity/integrity.toml` | Settings | Yes |
| `integrity_data/drafts/<batch>/` | Drafted cards and your review decisions | Yes |
| `integrity_data/sheets/sheet-vNNN.json` | Published answer sheets | **Yes** (they are your test) |
| `integrity_data/sheets/CHANGELOG.md` | What changed in each version | Yes |
| `integrity_data/runs/<run>/scorecard.md`, `failures.md`, `scorecard.json` | Report cards | Yes |
| `integrity_data/runs/<run>/raw.jsonl`, `grades.jsonl` | Raw answers and grading detail | No (already ignored) |

### 8.4 Discard and flag codes from `build`

| Code | Meaning |
|---|---|
| HC1 | The model said the paragraph is unsuitable |
| HC3 | Wrong number of key points |
| HC4 | A quote isn't in the paragraph exactly (often modernised spelling) |
| HC5 | A quote is too short or too long (6 to 40 words allowed) |
| HC6 | A quote crosses a chunk boundary |
| HC8 | A key point isn't the author's own view |
| HC9 | The question doesn't name the author |
| HC10 | A Burke quote sits inside quotation marks (someone else's words) |
| HC11 | A quote appears in more than one paragraph |
| `attribution_cue` (flag) | Phrases like "it may be objected", or an opponent's name. Check who is speaking |
| `rebuttal_next` (flag) | The next paragraph may argue against this one |
| `leakage` (flag) | The question copies words from the paragraph and may be too easy |
| `attribution_advice` (flag) | The speaker check thinks a key point may not be the author's view |
| `split_paragraph` (flag) | Information only |

### 8.5 Settings you may want to change (`integrity/integrity.toml`)

| Setting | Default | What it does |
|---|---|---|
| `[models] drafter` | `openai:gpt-4.1` | The model that drafts cards |
| `[models] attribution` | `anthropic:claude-opus-5-5` | The speaker check |
| `[models] judge` | `openai:gpt-4.1` | The grader. Keep it a different family from Agora's model |
| `[models] tracing` | `inherit` | Set to `off` to stop sending prompts to LangSmith |
| `[build] attribution_advisory` | `true` | Turn the speaker check off (not recommended) |
| `[build] default_count` / `default_false_premise` | 24 / 6 | Cards per build |
| `[publish] holdout_percent` | 15 | Share of sealed cards |
| `[quiz] min_cards` | 10 | The fewest cards a quiz will run on |

---

## 9. Rules of thumb

1. **Change one thing in Agora at a time,** then run the quiz. If you change three things, you won't know which one helped.
2. **Faithful and J5 are your hallucination meters.** A drop in either is the most important thing on the report card.
3. **Don't trust a single run's small differences.** One or two cards is noise. Look for consistent movement, or add more cards.
4. **Never tune Agora to specific failing cards.** Fix the general cause (search, prompt, citations), and watch the sealed cards for signs of teaching to the test.
5. **Keep growing the sheet.** When you notice Agora getting something wrong in normal use, build more cards from that author or book.
6. **The answer sheet is the ruler.** Don't edit published sheets. Retire bad cards and publish a new version.
7. **Treat the first run after any big change as a smoke test.** Run `--limit 3` first.
