# Scorecard r-20261125-025955

- Sheet: v002 (62 cards, 4 holdout), content `b788cd994d35`
- Grader: g-eaa3d7; judge: openai:gpt-4.1
- Agora: ask:answer_question · anthropic:claude-sonnet-5-5 · k=8 · ns epub-v1-ca56b9ef110f9669 · git d7f1f0e (dirty)
- Judged-metric trust: **UNTRUSTED**

## Headline (58 main cards)

| Metric | Value | Share |
|---|---|---|
| Found (right paragraph retrieved) | 45/49 | 92% |
| Complete (key points covered) (UNTRUSTED) | 87/116 | 75% |
| Faithful (claims supported) (UNTRUSTED) | 486/521 | 93% |
| Fully passing cards (UNTRUSTED) | 12/58 | 21% |

Errors: 0. Answers with no citations: 1. Wrongful refusals: 5.

## Retrieval

- hit rank distribution: rank 1: 33, rank 2: 7, rank 3: 2, rank 4: 1, rank 5: 1, rank 8: 1
- MRR: 0.77; near hits: 0
- evidence recall: 89%

## Citation integrity

- cited the anchor paragraph: 43/49
- quotes verified: 189/189
- trivial quotes: 8; invented ids: 0; label mismatches: 1; no citations: 1; self-check disagreements: 0

## Coverage and support (UNTRUSTED)

- coverage: covered 85, partial 4, absent 4, unverified 1, judge error 22
- support: supported 486, not supported 8, contradicted 0, unverified 9, judge error 18, uncited claims 216, unmapped inline citations (M13) 8
- answers with at least one unsupported claim: 24
- premise corrected: 8/9

## By author (UNTRUSTED)

| Author | Found | Complete | Faithful |
|---|---|---|---|
| Adam Smith | 6/6 | 9.5/12 (79%) | 60/64 (94%) |
| David Hume | 6/6 | 12/14 (86%) | 63/72 (88%) |
| Edmund Burke | 7/7 | 10/16 (62%) | 52/57 (91%) |
| Immanuel Kant | 5/8 | 12.5/18 (69%) | 91/94 (97%) |
| John Locke | 5/5 | 10/12 (83%) | 59/64 (92%) |
| John Stuart Mill | 4/4 | 10/12 (83%) | 57/59 (97%) |
| Mary Wollstonecraft | 6/6 | 12/14 (86%) | 58/59 (98%) |
| Thomas Hobbes | 6/7 | 11/18 (61%) | 46/52 (88%) |

## By work (UNTRUSTED)

| Work | Found | Complete | Faithful |
|---|---|---|---|
| A Vindication of the Rights of Woman | 6/6 | 12/14 (86%) | 58/59 (98%) |
| An Enquiry Concerning Human Understanding | 6/6 | 12/14 (86%) | 63/72 (88%) |
| An Essay Concerning Humane Understanding, Volume 1 / MDCXC, Based on the 2nd Edition, Books 1 and 2 | 3/3 | 6/6 (100%) | 30/33 (91%) |
| An Inquiry into the Nature and Causes of the Wealth of Nations | 6/6 | 9.5/12 (79%) | 60/64 (94%) |
| Fundamental Principles of the Metaphysic of Morals | 2/2 | 1.5/4 (38%) | 9/10 (90%) |
| Leviathan | 6/7 | 11/18 (61%) | 46/52 (88%) |
| On Liberty | 2/2 | 6/6 (100%) | 31/32 (97%) |
| Reflections on the Revolution in France | 7/7 | 10/16 (62%) | 52/57 (91%) |
| Second Treatise of Government | 2/2 | 4/6 (67%) | 29/31 (94%) |
| The Critique of Pure Reason | 3/6 | 11/14 (79%) | 82/84 (98%) |
| The Subjection of Women | 1/1 | 2/2 (100%) | 15/15 (100%) |
| Utilitarianism | 1/1 | 2/4 (50%) | 11/12 (92%) |

## Sealed holdout (4 cards, reported separately)

Found 3/3; Complete 100%; Faithful 91%; errors 0

## Grader health

- GRADER HEALTH  controls 8/24 must-pass ✗ · evidence rejected 13/1236 · claim coverage 0.93 · judge errors on 40 cards · trust UNTRUSTED
- consistency 3/148 (2%) · owner agreement: not yet calibrated (grader g-eaa3d7)

## Warnings

- corpus_version differs from the sheet's for 62 card(s): matching used text containment only
