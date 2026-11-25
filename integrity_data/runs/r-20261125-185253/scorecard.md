# Scorecard r-20261125-185253

- Sheet: v002 (62 cards, 4 holdout), content `b788cd994d35`
- Grader: g-eaa3d7; judge: openai:gpt-4.1
- Agora: ask:answer_question · anthropic:claude-sonnet-5-5 · k=8 · ns epub-v1-072397d01f31c73d · git d7f1f0e (dirty)
- Judged-metric trust: **TRUSTED**
- Regraded from r-20261125-025823

## Headline (58 main cards)

| Metric | Value | Share |
|---|---|---|
| Found (right paragraph retrieved) | 45/49 | 92% |
| Complete (key points covered) | 104/116 | 90% |
| Faithful (claims supported) | 590/616 | 96% |
| Fully passing cards | 16/58 | 28% |

Errors: 0. Answers with no citations: 1. Wrongful refusals: 7.

## Retrieval

- hit rank distribution: rank 1: 34, rank 2: 6, rank 3: 2, rank 4: 1, rank 5: 1, rank 8: 1
- MRR: 0.78; near hits: 0
- evidence recall: 89%

## Citation integrity

- cited the anchor paragraph: 41/49
- quotes verified: 170/170
- trivial quotes: 7; invented ids: 0; label mismatches: 0; no citations: 1; self-check disagreements: 0

## Coverage and support

- coverage: covered 102, partial 4, absent 7, unverified 3, judge error 0
- support: supported 590, not supported 8, contradicted 2, unverified 16, judge error 0, uncited claims 254, unmapped inline citations (M13) 8
- answers with at least one unsupported claim: 19
- premise corrected: 9/9

## By author

| Author | Found | Complete | Faithful |
|---|---|---|---|
| Adam Smith | 6/6 | 11/12 (92%) | 71/74 (96%) |
| David Hume | 6/6 | 14/14 (100%) | 73/75 (97%) |
| Edmund Burke | 7/7 | 16/16 (100%) | 75/80 (94%) |
| Immanuel Kant | 5/8 | 12.5/18 (69%) | 86/93 (92%) |
| John Locke | 5/5 | 10.5/12 (88%) | 75/76 (99%) |
| John Stuart Mill | 4/4 | 12/12 (100%) | 71/73 (97%) |
| Mary Wollstonecraft | 6/6 | 14/14 (100%) | 67/68 (99%) |
| Thomas Hobbes | 6/7 | 14/18 (78%) | 72/77 (94%) |

## By work

| Work | Found | Complete | Faithful |
|---|---|---|---|
| A Vindication of the Rights of Woman | 6/6 | 14/14 (100%) | 67/68 (99%) |
| An Enquiry Concerning Human Understanding | 6/6 | 14/14 (100%) | 73/75 (97%) |
| An Essay Concerning Humane Understanding, Volume 1 / MDCXC, Based on the 2nd Edition, Books 1 and 2 | 3/3 | 4.5/6 (75%) | 32/33 (97%) |
| An Inquiry into the Nature and Causes of the Wealth of Nations | 6/6 | 11/12 (92%) | 71/74 (96%) |
| Fundamental Principles of the Metaphysic of Morals | 2/2 | 4/4 (100%) | 15/16 (94%) |
| Leviathan | 6/7 | 14/18 (78%) | 72/77 (94%) |
| On Liberty | 2/2 | 6/6 (100%) | 37/38 (97%) |
| Reflections on the Revolution in France | 7/7 | 16/16 (100%) | 75/80 (94%) |
| Second Treatise of Government | 2/2 | 6/6 (100%) | 43/43 (100%) |
| The Critique of Pure Reason | 3/6 | 8.5/14 (61%) | 71/77 (92%) |
| The Subjection of Women | 1/1 | 2/2 (100%) | 14/14 (100%) |
| Utilitarianism | 1/1 | 4/4 (100%) | 20/21 (95%) |

## Sealed holdout (4 cards, reported separately)

Found 3/3; Complete 100%; Faithful 98%; errors 0

## Grader health

- GRADER HEALTH  controls 24/24 must-pass ✓ · evidence rejected 20/1670 · claim coverage 0.94 · trust TRUSTED
- consistency 170/172 (99%) · owner agreement: not yet calibrated (grader g-eaa3d7)

## Warnings

- corpus_version differs from the sheet's for 32 card(s): matching used text containment only
