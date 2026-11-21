# Scorecard r-20261121-093000

- Sheet: v001 (5 cards, 1 holdout), content `af62693ea0a7`
- Grader: g-golden; judge: openai:gpt-4.1
- Agora: ask:answer_question · anthropic:claude-sonnet-5-5 · k=8 · ns epub-v1-04b8672ea20df6c7 · git 1a2b3c4 (dirty)
- Judged-metric trust: **TRUSTED**

## Headline (4 main cards)

| Metric | Value | Share |
|---|---|---|
| Found (right paragraph retrieved) | 2/3 | 67% |
| Complete (key points covered) | 5/7 | 71% |
| Faithful (claims supported) | 8/9 | 89% |
| Fully passing cards | 1/3 | 33% |

Errors: 1. Answers with no citations: 0. Wrongful refusals: 0.

## Retrieval

- hit rank distribution: rank 1: 2
- MRR: 0.67; near hits: 0
- evidence recall: 67%

## Citation integrity

- cited the anchor paragraph: 2/3
- quotes verified: 8/8
- trivial quotes: 0; invented ids: 0; label mismatches: 0; no citations: 0; self-check disagreements: 0

## Coverage and support

- coverage: covered 5, partial 0, absent 2, unverified 0, judge error 0
- support: supported 8, not supported 1, contradicted 0, unverified 0, judge error 0, uncited claims 0, unmapped inline citations (M13) 0
- answers with at least one unsupported claim: 1
- premise corrected: 0/0

## By author

| Author | Found | Complete | Faithful |
|---|---|---|---|
| J. S. Mill | 0/1 | 0/2 (0%) | 3/3 (100%) |
| John Locke | 1/1 | 3/3 (100%) | 3/4 (75%) |
| Thomas Hobbes | 1/1 | 2/2 (100%) | 2/2 (100%) |

## By work

| Work | Found | Complete | Faithful |
|---|---|---|---|
| Leviathan | 1/1 | 2/2 (100%) | 2/2 (100%) |
| On Liberty | 0/1 | 0/2 (0%) | 3/3 (100%) |
| Second Treatise of Government | 1/1 | 3/3 (100%) | 3/4 (75%) |

## Sealed holdout (1 cards, reported separately)

Found 1/1; Complete 100%; Faithful 67%; errors 0

## Grader health

- GRADER HEALTH  controls 12/12 must-pass ✓ · evidence rejected 0/121 · claim coverage 0.98 · trust TRUSTED
- consistency 12/12 (100%) · owner agreement: not yet calibrated (grader g-golden)

## Warnings

- never retrieved during this run (is the book uploaded to the active namespace?): On Liberty
