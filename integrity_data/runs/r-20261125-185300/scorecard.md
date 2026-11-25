# Scorecard r-20261125-185300

- Sheet: v002 (62 cards, 4 holdout), content `b788cd994d35`
- Grader: g-eaa3d7; judge: openai:gpt-4.1
- Agora: ask:answer_question · anthropic:claude-sonnet-5-5 · k=8 · ns epub-v1-ca56b9ef110f9669 · git d7f1f0e (dirty)
- Judged-metric trust: **TRUSTED**
- Regraded from r-20261125-025955

## Headline (58 main cards)

| Metric | Value | Share |
|---|---|---|
| Found (right paragraph retrieved) | 45/49 | 92% |
| Complete (key points covered) | 105/116 | 91% |
| Faithful (claims supported) | 599/627 | 96% |
| Fully passing cards | 14/58 | 24% |

Errors: 0. Answers with no citations: 2. Wrongful refusals: 4.

## Retrieval

- hit rank distribution: rank 1: 33, rank 2: 7, rank 3: 2, rank 4: 1, rank 5: 1, rank 8: 1
- MRR: 0.77; near hits: 0
- evidence recall: 89%

## Citation integrity

- cited the anchor paragraph: 43/49
- quotes verified: 189/189
- trivial quotes: 8; invented ids: 0; label mismatches: 1; no citations: 2; self-check disagreements: 0

## Coverage and support

- coverage: covered 103, partial 4, absent 6, unverified 3, judge error 0
- support: supported 599, not supported 11, contradicted 1, unverified 16, judge error 0, uncited claims 254, unmapped inline citations (M13) 12
- answers with at least one unsupported claim: 21
- premise corrected: 9/9

## By author

| Author | Found | Complete | Faithful |
|---|---|---|---|
| Adam Smith | 6/6 | 9.5/12 (79%) | 67/72 (93%) |
| David Hume | 6/6 | 14/14 (100%) | 81/82 (99%) |
| Edmund Burke | 7/7 | 16/16 (100%) | 83/88 (94%) |
| Immanuel Kant | 5/8 | 14.5/18 (81%) | 101/104 (97%) |
| John Locke | 5/5 | 12/12 (100%) | 69/72 (96%) |
| John Stuart Mill | 4/4 | 11/12 (92%) | 67/68 (99%) |
| Mary Wollstonecraft | 6/6 | 14/14 (100%) | 61/63 (97%) |
| Thomas Hobbes | 6/7 | 14/18 (78%) | 70/78 (90%) |

## By work

| Work | Found | Complete | Faithful |
|---|---|---|---|
| A Vindication of the Rights of Woman | 6/6 | 14/14 (100%) | 61/63 (97%) |
| An Enquiry Concerning Human Understanding | 6/6 | 14/14 (100%) | 81/82 (99%) |
| An Essay Concerning Humane Understanding, Volume 1 / MDCXC, Based on the 2nd Edition, Books 1 and 2 | 3/3 | 6/6 (100%) | 30/32 (94%) |
| An Inquiry into the Nature and Causes of the Wealth of Nations | 6/6 | 9.5/12 (79%) | 67/72 (93%) |
| Fundamental Principles of the Metaphysic of Morals | 2/2 | 3.5/4 (88%) | 17/18 (94%) |
| Leviathan | 6/7 | 14/18 (78%) | 70/78 (90%) |
| On Liberty | 2/2 | 6/6 (100%) | 33/34 (97%) |
| Reflections on the Revolution in France | 7/7 | 16/16 (100%) | 83/88 (94%) |
| Second Treatise of Government | 2/2 | 6/6 (100%) | 39/40 (98%) |
| The Critique of Pure Reason | 3/6 | 11/14 (79%) | 84/86 (98%) |
| The Subjection of Women | 1/1 | 1/2 (50%) | 15/15 (100%) |
| Utilitarianism | 1/1 | 4/4 (100%) | 19/19 (100%) |

## Sealed holdout (4 cards, reported separately)

Found 3/3; Complete 100%; Faithful 85%; errors 0

## Grader health

- GRADER HEALTH  controls 24/24 must-pass ✓ · evidence rejected 22/1657 · claim coverage 0.93 · trust TRUSTED
- consistency 170/171 (99%) · owner agreement: not yet calibrated (grader g-eaa3d7)

## Warnings

- corpus_version differs from the sheet's for 62 card(s): matching used text containment only
