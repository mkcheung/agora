# Scorecard r-20261125-025823

- Sheet: v002 (62 cards, 4 holdout), content `b788cd994d35`
- Grader: g-eaa3d7; judge: openai:gpt-4.1
- Agora: ask:answer_question · anthropic:claude-sonnet-5-5 · k=8 · ns epub-v1-072397d01f31c73d · git d7f1f0e (dirty)
- Judged-metric trust: **UNTRUSTED**

## Headline (58 main cards)

| Metric | Value | Share |
|---|---|---|
| Found (right paragraph retrieved) | 45/49 | 92% |
| Complete (key points covered) (UNTRUSTED) | 93/116 | 80% |
| Faithful (claims supported) (UNTRUSTED) | 548/579 | 95% |
| Fully passing cards (UNTRUSTED) | 12/58 | 21% |

Errors: 0. Answers with no citations: 3. Wrongful refusals: 5.

## Retrieval

- hit rank distribution: rank 1: 34, rank 2: 6, rank 3: 2, rank 4: 1, rank 5: 1, rank 8: 1
- MRR: 0.78; near hits: 0
- evidence recall: 89%

## Citation integrity

- cited the anchor paragraph: 41/49
- quotes verified: 170/170
- trivial quotes: 7; invented ids: 0; label mismatches: 0; no citations: 3; self-check disagreements: 0

## Coverage and support (UNTRUSTED)

- coverage: covered 91, partial 4, absent 7, unverified 2, judge error 12
- support: supported 548, not supported 6, contradicted 2, unverified 14, judge error 9, uncited claims 246, unmapped inline citations (M13) 7
- answers with at least one unsupported claim: 24
- premise corrected: 9/9

## By author (UNTRUSTED)

| Author | Found | Complete | Faithful |
|---|---|---|---|
| Adam Smith | 6/6 | 11/12 (92%) | 69/74 (93%) |
| David Hume | 6/6 | 12/14 (86%) | 71/74 (96%) |
| Edmund Burke | 7/7 | 10/16 (62%) | 48/54 (89%) |
| Immanuel Kant | 5/8 | 12.5/18 (69%) | 89/93 (96%) |
| John Locke | 5/5 | 11.5/12 (96%) | 75/76 (99%) |
| John Stuart Mill | 4/4 | 10/12 (83%) | 62/65 (95%) |
| Mary Wollstonecraft | 6/6 | 12/14 (86%) | 57/61 (93%) |
| Thomas Hobbes | 6/7 | 14/18 (78%) | 77/82 (94%) |

## By work (UNTRUSTED)

| Work | Found | Complete | Faithful |
|---|---|---|---|
| A Vindication of the Rights of Woman | 6/6 | 12/14 (86%) | 57/61 (93%) |
| An Enquiry Concerning Human Understanding | 6/6 | 12/14 (86%) | 71/74 (96%) |
| An Essay Concerning Humane Understanding, Volume 1 / MDCXC, Based on the 2nd Edition, Books 1 and 2 | 3/3 | 5.5/6 (92%) | 31/32 (97%) |
| An Inquiry into the Nature and Causes of the Wealth of Nations | 6/6 | 11/12 (92%) | 69/74 (93%) |
| Fundamental Principles of the Metaphysic of Morals | 2/2 | 4/4 (100%) | 16/16 (100%) |
| Leviathan | 6/7 | 14/18 (78%) | 77/82 (94%) |
| On Liberty | 2/2 | 6/6 (100%) | 36/38 (95%) |
| Reflections on the Revolution in France | 7/7 | 10/16 (62%) | 48/54 (89%) |
| Second Treatise of Government | 2/2 | 6/6 (100%) | 44/44 (100%) |
| The Critique of Pure Reason | 3/6 | 8.5/14 (61%) | 73/77 (95%) |
| The Subjection of Women | 1/1 | 2/2 (100%) | 14/14 (100%) |
| Utilitarianism | 1/1 | 2/4 (50%) | 12/13 (92%) |

## Sealed holdout (4 cards, reported separately)

Found 3/3; Complete 100%; Faithful 98%; errors 0

## Grader health

- GRADER HEALTH  controls 8/24 must-pass ✗ · evidence rejected 17/1398 · claim coverage 0.95 · judge errors on 35 cards · trust UNTRUSTED
- consistency 1/162 (1%) · owner agreement: not yet calibrated (grader g-eaa3d7)

## Warnings

- corpus_version differs from the sheet's for 32 card(s): matching used text containment only
