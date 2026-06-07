# Reproducible Task Corpus

The bundled `duckdb-v1` corpus defines small, reproducible rewrite-search
problems. It is installed with the Python package and can be loaded without
depending on the repository checkout location:

```python
from pathlib import Path

from snowprove.corpora import bundled_corpus_path
from snowprove.corpus import load_task_corpus, materialize_corpus_fixtures

corpus = load_task_corpus(bundled_corpus_path())
materialize_corpus_fixtures(corpus, Path("snowprove-corpus-data"))
```

The corpus runner executes search baselines and writes a versioned comparison
artifact:

```bash
uv run snowprove corpus run snowprove-runs/corpus
```

For a short smoke run:

```bash
uv run snowprove corpus run snowprove-runs/corpus-smoke \
  --task distinct-and-not-null \
  --strategy fixed_order \
  --strategy greedy \
  --warmups 0 \
  --repetitions 1
```

Useful controls include `--random-seed`, `--beam-width`, `--max-nodes`,
`--threads`, `--timeout`, `--manifest`, and `--report-file`. Fixture databases
and content-addressed oracle caches are retained under the output directory, so
repeated runs reuse both.

The manifest separates named DuckDB fixture profiles from task definitions.
Multiple tasks can therefore share one generated database.

Each task pins:

- SQL and trusted constraint files
- a seeded fixture profile
- enabled rewrite rules
- maximum environment steps
- descriptive tags
- expected verifier backends

The loader rejects duplicate IDs, unknown fixtures or rules, missing files,
absolute paths, and paths escaping the corpus directory. It returns an
`EnvironmentTask` for execution plus corpus provenance.

## Fingerprints

Every loaded task has a SHA-256 content fingerprint over:

- normalized query text
- parsed trusted constraints
- fixture specification
- task definition and dialect

The corpus fingerprint includes the manifest and ordered task fingerprints.
Checkout paths do not affect either fingerprint. These IDs should be included
in benchmark caches, trajectory records, and comparison reports.

## Bundled duckdb-v1 Corpus

The bundled corpus contains five hand-written anchor tasks:

- redundant `DISTINCT` removal
- redundant non-null filter removal
- unused `LEFT JOIN` removal
- `JOIN` plus `DISTINCT` to `EXISTS`
- a multi-action `DISTINCT` plus non-null-filter task

It also expands five task families across query variants and contrasting
fixture profiles, producing 25 concrete tasks total. The generated families
cover:

- redundant `DISTINCT`
- redundant non-null filters
- unused `LEFT JOIN`
- `JOIN` plus `DISTINCT` to `EXISTS`
- multi-action `DISTINCT` plus non-null-filter cases

Four fixture profiles vary seed, selectivity, duplicates, nulls, and join skew.
This is still a small foundation set, not yet a statistically useful training
set.

## Run Artifacts

The `corpus_search_run` JSON artifact records:

- complete per-task `SearchResult` paths
- cumulative reward and explored nodes
- verifier and benchmark requests, cache hits, and real cache misses
- elapsed time and failure details for each task-strategy pair
- aggregate completion, mean reward, explored-node, oracle-call, and elapsed
  metrics by strategy
- corpus/task fingerprints and Python, DuckDB, and platform versions

Cache namespaces are isolated by task and strategy. Search branches within one
strategy share cached oracle work, but a strategy does not receive artificially
low miss counts because another strategy ran first. A failed strategy is
recorded without aborting the remaining report; the CLI exits nonzero after
writing the artifact if any strategy failed.

## Adding Tasks

Prefer adding variations systematically rather than copying arbitrary SQL.
Each new task should change a named experimental dimension such as:

- table size
- filter selectivity
- duplicate or null rate
- join skew
- available action count
- rewrite ordering
- beneficial, neutral, or harmful equivalent rewrites

Tests should confirm that each task parses and exposes at least one action under
its declared rule set.
