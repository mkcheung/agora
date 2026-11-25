# Scorecard r-20261125-185309

- Sheet: v002 (62 cards, 4 holdout), content `b788cd994d35`
- Grader: g-eaa3d7; judge: openai:gpt-4.1
- Agora: ask:answer_question · anthropic:claude-sonnet-5-5 · k=8 · ns epub-v1-6e66750471be0619 · git d7f1f0e (dirty)
- Judged-metric trust: **TRUSTED**
- Regraded from r-20261125-030003

## Headline (58 main cards)

| Metric | Value | Share |
|---|---|---|
| Found (right paragraph retrieved) | 48/49 | 98% |
| Complete (key points covered) | 112/116 | 97% |
| Faithful (claims supported) | 632/653 | 97% |
| Fully passing cards | 18/58 | 31% |

Errors: 0. Answers with no citations: 2. Wrongful refusals: 7.

## Retrieval

- hit rank distribution: rank 1: 34, rank 2: 6, rank 3: 4, rank 4: 2, rank 5: 2
- MRR: 0.80; near hits: 0
- evidence recall: 96%

## Citation integrity

- cited the anchor paragraph: 44/49
- quotes verified: 195/196
- trivial quotes: 5; invented ids: 0; label mismatches: 0; no citations: 2; self-check disagreements: 0

## Coverage and support

- coverage: covered 111, partial 2, absent 2, unverified 1, judge error 0
- support: supported 632, not supported 7, contradicted 2, unverified 12, judge error 0, uncited claims 270, unmapped inline citations (M13) 8
- answers with at least one unsupported claim: 17
- premise corrected: 9/9

## By author

| Author | Found | Complete | Faithful |
|---|---|---|---|
| Adam Smith | 6/6 | 11/12 (92%) | 68/72 (94%) |
| David Hume | 6/6 | 14/14 (100%) | 81/84 (96%) |
| Edmund Burke | 7/7 | 15.5/16 (97%) | 83/84 (99%) |
| Immanuel Kant | 7/8 | 16.5/18 (92%) | 107/112 (96%) |
| John Locke | 5/5 | 11/12 (92%) | 72/74 (97%) |
| John Stuart Mill | 4/4 | 12/12 (100%) | 71/72 (99%) |
| Mary Wollstonecraft | 6/6 | 14/14 (100%) | 70/72 (97%) |
| Thomas Hobbes | 7/7 | 18/18 (100%) | 80/83 (96%) |

## By work

| Work | Found | Complete | Faithful |
|---|---|---|---|
| A Vindication of the Rights of Woman | 6/6 | 14/14 (100%) | 70/72 (97%) |
| An Enquiry Concerning Human Understanding | 6/6 | 14/14 (100%) | 81/84 (96%) |
| An Essay Concerning Humane Understanding, Volume 1 / MDCXC, Based on the 2nd Edition, Books 1 and 2 | 3/3 | 5/6 (83%) | 30/31 (97%) |
| An Inquiry into the Nature and Causes of the Wealth of Nations | 6/6 | 11/12 (92%) | 68/72 (94%) |
| Fundamental Principles of the Metaphysic of Morals | 2/2 | 4/4 (100%) | 17/20 (85%) |
| Leviathan | 7/7 | 18/18 (100%) | 80/83 (96%) |
| On Liberty | 2/2 | 6/6 (100%) | 38/39 (97%) |
| Reflections on the Revolution in France | 7/7 | 15.5/16 (97%) | 83/84 (99%) |
| Second Treatise of Government | 2/2 | 6/6 (100%) | 42/43 (98%) |
| The Critique of Pure Reason | 5/6 | 12.5/14 (89%) | 90/92 (98%) |
| The Subjection of Women | 1/1 | 2/2 (100%) | 13/13 (100%) |
| Utilitarianism | 1/1 | 4/4 (100%) | 20/20 (100%) |

## Sealed holdout (4 cards, reported separately)

Found 3/3; Complete 88%; Faithful 89%; errors 0

## Grader health

- GRADER HEALTH  controls 24/24 must-pass ✓ · evidence rejected 19/1764 · claim coverage 0.94 · trust TRUSTED
- consistency 179/180 (99%) · owner agreement: not yet calibrated (grader g-eaa3d7)

## Warnings

- corpus_version differs from the sheet's for 62 card(s): matching used text containment only
