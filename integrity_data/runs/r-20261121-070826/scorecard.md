# Scorecard r-20261121-070826

- Sheet: v001 (32 cards, 3 holdout), content `9f70dc8d87be`
- Grader: g-b447cd; judge: openai:gpt-4.1
- Agora: ask:answer_question · anthropic:claude-sonnet-5-5 · k=8 · ns epub-v1-04b8672ea20df6c7 · git 2a9a839
- Judged-metric trust: **TRUSTED**

## Headline (29 main cards)

| Metric | Value | Share |
|---|---|---|
| Found (right paragraph retrieved) | 22/23 | 96% |
| Complete (key points covered) | 54/58 | 93% |
| Faithful (claims supported) | 286/301 | 95% |
| Fully passing cards | 8/29 | 28% |

Errors: 0. Answers with no citations: 1. Wrongful refusals: 3.

## Retrieval

- hit rank distribution: rank 1: 17, rank 2: 3, rank 3: 1, rank 4: 1
- MRR: 0.83; near hits: 0
- evidence recall: 90%

## Citation integrity

- cited the anchor paragraph: 21/23
- quotes verified: 92/92
- trivial quotes: 3; invented ids: 0; label mismatches: 1; no citations: 1; self-check disagreements: 0

## Coverage and support

- coverage: covered 54, partial 0, absent 4, unverified 0, judge error 0
- support: supported 286, not supported 2, contradicted 0, unverified 13, judge error 0, uncited claims 117, unmapped inline citations (M13) 16
- answers with at least one unsupported claim: 9
- premise corrected: 6/6

## By author

| Author | Found | Complete | Faithful |
|---|---|---|---|
| Edmund Burke | 7/7 | 16/16 (100%) | 77/79 (97%) |
| John Locke | 5/5 | 12/12 (100%) | 58/62 (94%) |
| John Stuart Mill | 4/4 | 12/12 (100%) | 73/76 (96%) |
| Thomas Hobbes | 6/7 | 14/18 (78%) | 78/84 (93%) |

## By work

| Work | Found | Complete | Faithful |
|---|---|---|---|
| An Essay Concerning Humane Understanding, Volume 1 / MDCXC, Based on the 2nd Edition, Books 1 and 2 | 3/3 | 6/6 (100%) | 26/26 (100%) |
| Leviathan | 6/7 | 14/18 (78%) | 78/84 (93%) |
| On Liberty | 2/2 | 6/6 (100%) | 40/42 (95%) |
| Reflections on the Revolution in France | 7/7 | 16/16 (100%) | 77/79 (97%) |
| Second Treatise of Government | 2/2 | 6/6 (100%) | 32/36 (89%) |
| The Subjection of Women | 1/1 | 2/2 (100%) | 14/14 (100%) |
| Utilitarianism | 1/1 | 4/4 (100%) | 19/20 (95%) |

## Sealed holdout (3 cards, reported separately)

Found 3/3; Complete 100%; Faithful 88%; errors 0

## Grader health

- GRADER HEALTH  controls 24/24 must-pass ✓ · evidence rejected 16/903 · claim coverage 0.95 · trust TRUSTED
- consistency 86/86 (100%) · owner agreement: not yet calibrated (grader g-b447cd)
