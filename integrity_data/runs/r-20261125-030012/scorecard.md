# Scorecard r-20261125-030012

- Sheet: v002 (62 cards, 4 holdout), content `b788cd994d35`
- Grader: g-eaa3d7; judge: openai:gpt-4.1
- Agora: ask:answer_question · anthropic:claude-sonnet-5-5 · k=8 · ns epub-v1-493ca312bc082c7e · git d7f1f0e (dirty)
- Judged-metric trust: **UNTRUSTED**

## Headline (58 main cards)

| Metric | Value | Share |
|---|---|---|
| Found (right paragraph retrieved) | 48/49 | 98% |
| Complete (key points covered) (UNTRUSTED) | 89/116 | 77% |
| Faithful (claims supported) (UNTRUSTED) | 479/525 | 91% |
| Fully passing cards (UNTRUSTED) | 14/58 | 24% |

Errors: 0. Answers with no citations: 3. Wrongful refusals: 4.

## Retrieval

- hit rank distribution: rank 1: 34, rank 2: 6, rank 3: 4, rank 4: 3, rank 5: 1
- MRR: 0.80; near hits: 0
- evidence recall: 96%

## Citation integrity

- cited the anchor paragraph: 44/49
- quotes verified: 194/195
- trivial quotes: 7; invented ids: 1; label mismatches: 0; no citations: 3; self-check disagreements: 0

## Coverage and support (UNTRUSTED)

- coverage: covered 88, partial 2, absent 1, unverified 3, judge error 22
- support: supported 479, not supported 7, contradicted 0, unverified 15, judge error 24, uncited claims 212, unmapped inline citations (M13) 13
- answers with at least one unsupported claim: 27
- premise corrected: 8/9

## By author (UNTRUSTED)

| Author | Found | Complete | Faithful |
|---|---|---|---|
| Adam Smith | 6/6 | 10/12 (83%) | 65/70 (93%) |
| David Hume | 6/6 | 11/14 (79%) | 59/73 (81%) |
| Edmund Burke | 7/7 | 10/16 (62%) | 33/39 (85%) |
| Immanuel Kant | 7/8 | 12/18 (67%) | 80/86 (93%) |
| John Locke | 5/5 | 10/12 (83%) | 65/67 (97%) |
| John Stuart Mill | 4/4 | 10/12 (83%) | 66/67 (99%) |
| Mary Wollstonecraft | 6/6 | 12/14 (86%) | 54/58 (93%) |
| Thomas Hobbes | 7/7 | 14/18 (78%) | 57/65 (88%) |

## By work (UNTRUSTED)

| Work | Found | Complete | Faithful |
|---|---|---|---|
| A Vindication of the Rights of Woman | 6/6 | 12/14 (86%) | 54/58 (93%) |
| An Enquiry Concerning Human Understanding | 6/6 | 11/14 (79%) | 59/73 (81%) |
| An Essay Concerning Humane Understanding, Volume 1 / MDCXC, Based on the 2nd Edition, Books 1 and 2 | 3/3 | 6/6 (100%) | 36/36 (100%) |
| An Inquiry into the Nature and Causes of the Wealth of Nations | 6/6 | 10/12 (83%) | 65/70 (93%) |
| Fundamental Principles of the Metaphysic of Morals | 2/2 | 0.5/4 (12%) | 5/7 (71%) |
| Leviathan | 7/7 | 14/18 (78%) | 57/65 (88%) |
| On Liberty | 2/2 | 6/6 (100%) | 38/38 (100%) |
| Reflections on the Revolution in France | 7/7 | 10/16 (62%) | 33/39 (85%) |
| Second Treatise of Government | 2/2 | 4/6 (67%) | 29/31 (94%) |
| The Critique of Pure Reason | 5/6 | 11.5/14 (82%) | 75/79 (95%) |
| The Subjection of Women | 1/1 | 2/2 (100%) | 15/15 (100%) |
| Utilitarianism | 1/1 | 2/4 (50%) | 13/14 (93%) |

## Sealed holdout (4 cards, reported separately)

Found 3/3; Complete 100%; Faithful 91%; errors 0

## Grader health

- GRADER HEALTH  controls 8/24 must-pass ✗ · evidence rejected 22/1256 · claim coverage 0.94 · judge errors on 40 cards · trust UNTRUSTED
- consistency 5/151 (3%) · owner agreement: not yet calibrated (grader g-eaa3d7)

## Warnings

- corpus_version differs from the sheet's for 62 card(s): matching used text containment only
