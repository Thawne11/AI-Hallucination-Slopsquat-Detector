# Scanner accuracy benchmark

Measured against `benchmark/corpus.py`, replaying registry answers recorded in `benchmark/snapshot.json`. Offline and deterministic.

Every case class below exists because the scanner got that class wrong at some point during development.

## Classification (does this name have a real distribution?)

- **Precision 100%** -- 0 legitimate package(s) wrongly flagged
- **Recall 100%** -- 0 name(s) that should have been flagged and were not
- 51/51 cases classified correctly

| Case class | Correct | Total |
|---|---|---|
| ambiguous_import | 1 | 1 |
| hallucinated | 10 | 10 |
| import_alias | 13 | 13 |
| import_identity | 4 | 4 |
| invented_plausible | 5 | 5 |
| real_popular | 18 | 18 |

No misclassifications.

## Structural (project shapes that caused false positives)

| Project | Findings | Expected | |
|---|---|---|---|
| test_fixtures | 0 | 0 | ok |
| monorepo_siblings | 0 | 0 | ok |
| grpc_stubs | 0 | 0 | ok |
| local_modules | 0 | 0 | ok |
| stdlib_and_relative | 0 | 0 | ok |
| manifest_is_literal | 1 | 1 | ok |
| invented_import | 1 | 1 | ok |

## Risk ranking (real packages that should score as risky)

| Package | Tier | Score | |
|---|---|---|---|
| loadsh | MEDIUM | 40 | ok |

## What this does and does not measure

The corpus is hand-labelled and small. It measures whether the scanner still handles the cases it is *known* to have got wrong, plus a sample of ordinary packages it must leave alone. It cannot measure error classes nobody has thought of yet -- which is exactly the category every one of these entries came from originally.

Risk *scores* are not scored for correctness. There is no ground truth for "is 40/100 the right number", so only the ranking claim is checked: a known typosquat must land above LOW.

