# Scorecard r-20261125-030003

- Sheet: v002 (62 cards, 4 holdout), content `b788cd994d35`
- Grader: g-eaa3d7; judge: openai:gpt-4.1
- Agora: ask:answer_question · anthropic:claude-sonnet-5-5 · k=8 · ns epub-v1-6e66750471be0619 · git d7f1f0e (dirty)
- Judged-metric trust: **UNTRUSTED**

## Headline (58 main cards)

| Metric | Value | Share |
|---|---|---|
| Found (right paragraph retrieved) | 48/49 | 98% |
| Complete (key points covered) (UNTRUSTED) | 93/116 | 80% |
| Faithful (claims supported) (UNTRUSTED) | 504/531 | 95% |
| Fully passing cards (UNTRUSTED) | 16/58 | 28% |

Errors: 0. Answers with no citations: 3. Wrongful refusals: 5.

## Retrieval

- hit rank distribution: rank 1: 34, rank 2: 6, rank 3: 4, rank 4: 2, rank 5: 2
- MRR: 0.80; near hits: 0
- evidence recall: 96%

## Citation integrity

- cited the anchor paragraph: 44/49
- quotes verified: 195/196
- trivial quotes: 5; invented ids: 0; label mismatches: 0; no citations: 3; self-check disagreements: 0

## Coverage and support (UNTRUSTED)

- coverage: covered 92, partial 2, absent 1, unverified 1, judge error 20
- support: supported 504, not supported 3, contradicted 3, unverified 10, judge error 11, uncited claims 223, unmapped inline citations (M13) 8
- answers with at least one unsupported claim: 23
- premise corrected: 8/9

## By author (UNTRUSTED)

| Author | Found | Complete | Faithful |
|---|---|---|---|
| Adam Smith | 6/6 | 10/12 (83%) | 62/65 (95%) |
| David Hume | 6/6 | 12/14 (86%) | 66/71 (93%) |
| Edmund Burke | 7/7 | 9.5/16 (59%) | 44/47 (94%) |
| Immanuel Kant | 7/8 | 14.5/18 (81%) | 95/100 (95%) |
| John Locke | 5/5 | 9/12 (75%) | 68/71 (96%) |
| John Stuart Mill | 4/4 | 10/12 (83%) | 63/65 (97%) |
| Mary Wollstonecraft | 6/6 | 12/14 (86%) | 59/62 (95%) |
| Thomas Hobbes | 7/7 | 16/18 (89%) | 47/50 (94%) |

## By work (UNTRUSTED)

| Work | Found | Complete | Faithful |
|---|---|---|---|
| A Vindication of the Rights of Woman | 6/6 | 12/14 (86%) | 59/62 (95%) |
| An Enquiry Concerning Human Understanding | 6/6 | 12/14 (86%) | 66/71 (93%) |
| An Essay Concerning Humane Understanding, Volume 1 / MDCXC, Based on the 2nd Edition, Books 1 and 2 | 3/3 | 5/6 (83%) | 36/37 (97%) |
| An Inquiry into the Nature and Causes of the Wealth of Nations | 6/6 | 10/12 (83%) | 62/65 (95%) |
| Fundamental Principles of the Metaphysic of Morals | 2/2 | 2/4 (50%) | 7/10 (70%) |
| Leviathan | 7/7 | 16/18 (89%) | 47/50 (94%) |
| On Liberty | 2/2 | 6/6 (100%) | 38/39 (97%) |
| Reflections on the Revolution in France | 7/7 | 9.5/16 (59%) | 44/47 (94%) |
| Second Treatise of Government | 2/2 | 4/6 (67%) | 32/34 (94%) |
| The Critique of Pure Reason | 5/6 | 12.5/14 (89%) | 88/90 (98%) |
| The Subjection of Women | 1/1 | 2/2 (100%) | 13/13 (100%) |
| Utilitarianism | 1/1 | 2/4 (50%) | 12/13 (92%) |

## Sealed holdout (4 cards, reported separately)

Found 3/3; Complete 88%; Faithful 90%; errors 0

## Grader health

- GRADER HEALTH  controls 8/24 must-pass ✗ · evidence rejected 17/1305 · claim coverage 0.95 · judge errors on 39 cards · trust UNTRUSTED
- consistency 3/153 (2%) · owner agreement: not yet calibrated (grader g-eaa3d7)

## Warnings

- corpus_version differs from the sheet's for 62 card(s): matching used text containment only
