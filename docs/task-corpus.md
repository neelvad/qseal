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

## Bundled v1 Tasks

The initial corpus contains five tasks:

- redundant `DISTINCT` removal
- redundant non-null filter removal
- unused `LEFT JOIN` removal
- `JOIN` plus `DISTINCT` to `EXISTS`
- a multi-action `DISTINCT` plus non-null-filter task

Two fixture profiles vary seed, selectivity, duplicates, nulls, and join skew.
This is a format and runner foundation, not yet a statistically useful training
set. The next milestone is a corpus runner that executes every search baseline
and records reward, path, oracle calls, benchmark calls, and elapsed time.

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
