# Scorecard r-20261125-185316

- Sheet: v002 (62 cards, 4 holdout), content `b788cd994d35`
- Grader: g-eaa3d7; judge: openai:gpt-4.1
- Agora: ask:answer_question · anthropic:claude-sonnet-5-5 · k=8 · ns epub-v1-493ca312bc082c7e · git d7f1f0e (dirty)
- Judged-metric trust: **TRUSTED**
- Regraded from r-20261125-030012

## Headline (58 main cards)

| Metric | Value | Share |
|---|---|---|
| Found (right paragraph retrieved) | 48/49 | 98% |
| Complete (key points covered) | 105.5/116 | 91% |
| Faithful (claims supported) | 603/631 | 96% |
| Fully passing cards | 15/58 | 26% |

Errors: 0. Answers with no citations: 3. Wrongful refusals: 6.

## Retrieval

- hit rank distribution: rank 1: 34, rank 2: 6, rank 3: 4, rank 4: 3, rank 5: 1
- MRR: 0.80; near hits: 0
- evidence recall: 96%

## Citation integrity

- cited the anchor paragraph: 44/49
- quotes verified: 194/195
- trivial quotes: 7; invented ids: 1; label mismatches: 0; no citations: 3; self-check disagreements: 0

## Coverage and support

- coverage: covered 104, partial 3, absent 4, unverified 5, judge error 0
- support: supported 603, not supported 6, contradicted 0, unverified 22, judge error 0, uncited claims 240, unmapped inline citations (M13) 13
- answers with at least one unsupported claim: 18
- premise corrected: 9/9

## By author

| Author | Found | Complete | Faithful |
|---|---|---|---|
| Adam Smith | 6/6 | 11/12 (92%) | 82/86 (95%) |
| David Hume | 6/6 | 14/14 (100%) | 76/79 (96%) |
| Edmund Burke | 7/7 | 16/16 (100%) | 56/59 (95%) |
| Immanuel Kant | 7/8 | 13/18 (72%) | 90/95 (95%) |
| John Locke | 5/5 | 12/12 (100%) | 75/76 (99%) |
| John Stuart Mill | 4/4 | 12/12 (100%) | 75/75 (100%) |
| Mary Wollstonecraft | 6/6 | 12.5/14 (89%) | 68/71 (96%) |
| Thomas Hobbes | 7/7 | 15/18 (83%) | 81/90 (90%) |

## By work

| Work | Found | Complete | Faithful |
|---|---|---|---|
| A Vindication of the Rights of Woman | 6/6 | 12.5/14 (89%) | 68/71 (96%) |
| An Enquiry Concerning Human Understanding | 6/6 | 14/14 (100%) | 76/79 (96%) |
| An Essay Concerning Humane Understanding, Volume 1 / MDCXC, Based on the 2nd Edition, Books 1 and 2 | 3/3 | 6/6 (100%) | 36/36 (100%) |
| An Inquiry into the Nature and Causes of the Wealth of Nations | 6/6 | 11/12 (92%) | 82/86 (95%) |
| Fundamental Principles of the Metaphysic of Morals | 2/2 | 1.5/4 (38%) | 16/19 (84%) |
| Leviathan | 7/7 | 15/18 (83%) | 81/90 (90%) |
| On Liberty | 2/2 | 6/6 (100%) | 37/37 (100%) |
| Reflections on the Revolution in France | 7/7 | 16/16 (100%) | 56/59 (95%) |
| Second Treatise of Government | 2/2 | 6/6 (100%) | 39/40 (98%) |
| The Critique of Pure Reason | 5/6 | 11.5/14 (82%) | 74/76 (97%) |
| The Subjection of Women | 1/1 | 2/2 (100%) | 16/16 (100%) |
| Utilitarianism | 1/1 | 4/4 (100%) | 22/22 (100%) |

## Sealed holdout (4 cards, reported separately)

Found 3/3; Complete 100%; Faithful 96%; errors 0

## Grader health

- GRADER HEALTH  controls 24/24 must-pass ✓ · evidence rejected 29/1700 · claim coverage 0.94 · trust TRUSTED
- consistency 171/174 (98%) · owner agreement: not yet calibrated (grader g-eaa3d7)

## Warnings

- corpus_version differs from the sheet's for 62 card(s): matching used text containment only
