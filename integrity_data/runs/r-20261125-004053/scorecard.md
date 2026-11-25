# Scorecard r-20261125-004053

- Sheet: v001 (32 cards, 3 holdout), content `9f70dc8d87be`
- Grader: g-eaa3d7; judge: openai:gpt-4.1
- Agora: ask:answer_question · anthropic:claude-sonnet-5-5 · k=8 · ns epub-v1-072397d01f31c73d · git 60de7c8 (dirty)
- Judged-metric trust: **TRUSTED**

## Headline (29 main cards)

| Metric | Value | Share |
|---|---|---|
| Found (right paragraph retrieved) | 22/23 | 96% |
| Complete (key points covered) | 54/58 | 93% |
| Faithful (claims supported) | 307/320 | 96% |
| Fully passing cards | 8/29 | 28% |

Errors: 0. Answers with no citations: 2. Wrongful refusals: 2.

## Retrieval

- hit rank distribution: rank 1: 17, rank 2: 3, rank 3: 1, rank 4: 1
- MRR: 0.83; near hits: 0
- evidence recall: 90%

## Citation integrity

- cited the anchor paragraph: 20/23
- quotes verified: 78/78
- trivial quotes: 2; invented ids: 0; label mismatches: 1; no citations: 2; self-check disagreements: 0

## Coverage and support

- coverage: covered 54, partial 0, absent 3, unverified 1, judge error 0
- support: supported 307, not supported 7, contradicted 0, unverified 6, judge error 0, uncited claims 140, unmapped inline citations (M13) 5
- answers with at least one unsupported claim: 11
- premise corrected: 6/6

## By author

| Author | Found | Complete | Faithful |
|---|---|---|---|
| Edmund Burke | 7/7 | 16/16 (100%) | 79/83 (95%) |
| John Locke | 5/5 | 11/12 (92%) | 79/81 (98%) |
| John Stuart Mill | 4/4 | 12/12 (100%) | 76/77 (99%) |
| Thomas Hobbes | 6/7 | 15/18 (83%) | 73/79 (92%) |

## By work

| Work | Found | Complete | Faithful |
|---|---|---|---|
| An Essay Concerning Humane Understanding, Volume 1 / MDCXC, Based on the 2nd Edition, Books 1 and 2 | 3/3 | 6/6 (100%) | 38/39 (97%) |
| Leviathan | 6/7 | 15/18 (83%) | 73/79 (92%) |
| On Liberty | 2/2 | 6/6 (100%) | 43/44 (98%) |
| Reflections on the Revolution in France | 7/7 | 16/16 (100%) | 79/83 (95%) |
| Second Treatise of Government | 2/2 | 5/6 (83%) | 41/42 (98%) |
| The Subjection of Women | 1/1 | 2/2 (100%) | 14/14 (100%) |
| Utilitarianism | 1/1 | 4/4 (100%) | 19/19 (100%) |

## Sealed holdout (3 cards, reported separately)

Found 3/3; Complete 100%; Faithful 100%; errors 0

## Grader health

- GRADER HEALTH  controls 24/24 must-pass ✓ · evidence rejected 7/960 · claim coverage 0.94 · trust TRUSTED
- consistency 90/92 (98%) · owner agreement: not yet calibrated (grader g-eaa3d7)

## Warnings

- corpus_version differs from the sheet's for 32 card(s): matching used text containment only
