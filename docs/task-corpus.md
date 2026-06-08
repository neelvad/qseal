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
`--reward-margin`, `--minimum-duration-ms`, `--threads`, `--timeout`,
`--manifest`, and `--report-file`. Fixture databases and content-addressed
oracle caches are retained under the output directory, so repeated runs reuse
both.

Use `--reward-margin` to require a meaningful cumulative improvement before
greedy, beam, or exhaustive search prefers a longer path:

```bash
uv run snowprove corpus run snowprove-runs/corpus-margin \
  --reward-margin 0.05 \
  --warmups 2 \
  --repetitions 5
```

The measured rewards remain unchanged in artifacts. The margin only changes
search selection. Fixed-order and random remain forced-rollout baselines.

Use `--minimum-duration-ms` to amortize timer and scheduler noise for fast
queries:

```bash
uv run snowprove corpus run snowprove-runs/corpus-confidence \
  --minimum-duration-ms 5.0 \
  --reward-margin 0.05
```

Snowprove calibrates each query independently, repeats it enough times to reach
the target duration, and divides the batch time back into a per-execution
latency. Artifacts record both batch timings and executions per sample. A
transition receives zero reward only if the batching safety cap still cannot
reach the requested duration.

For repeated independent measurements and an automatic stability aggregate:

```bash
uv run snowprove corpus repeat snowprove-runs/corpus-repeat \
  --runs 3 \
  --reward-margin 0.05 \
  --minimum-duration-ms 5.0 \
  --warmups 2 \
  --repetitions 5
```

This creates `run-001/`, `run-002/`, and so on, each with an isolated
content-addressed benchmark cache, then writes `corpus-aggregate.json`.
Existing reports are never overwritten because reusing their caches would
invalidate measurement independence.

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

It also expands six task families across query variants and contrasting
fixture profiles, producing 53 concrete tasks total. The generated families
cover:

- redundant `DISTINCT`
- redundant non-null filters
- unused `LEFT JOIN`
- `JOIN` plus `DISTINCT` to `EXISTS`
- multi-action `DISTINCT` plus non-null-filter cases
- predicate pushdown through simple projection subqueries

Six fixture profiles vary table scale, seed, selectivity, duplicates, nulls,
and join skew. Two scale profiles apply the standard distribution to compact
and medium table sizes. Predicate-pushdown variants include fixture-controlled
active-user selectivity and a selective high-value-order filter.

The corpus is large enough for baseline and harness development, but remains a
foundation set rather than a statistically useful training set.

## Run Artifacts

The `corpus_search_run` JSON artifact records:

- complete per-task `SearchResult` paths
- cumulative reward and explored nodes
- verifier and benchmark requests, cache hits, and real cache misses
- elapsed time and failure details for each task-strategy pair
- aggregate completion, mean reward, explored-node, oracle-call, and elapsed
  metrics by strategy
- corpus/task fingerprints and Python, DuckDB, and platform versions

Cache namespaces are isolated by task and shared across strategies. Every
unique SQL transition therefore receives one verifier result and one benchmark
result per uncached corpus run, so strategies compare the same reward instead
of independently remeasuring identical work. Per-strategy metrics still record
logical requests, cache hits, and physical misses; each task also records total
unique verifier and benchmark executions.

A failed strategy is recorded without aborting the remaining report; the CLI
exits nonzero after writing the artifact if any strategy failed.

## Summarizing Runs

Use the summary command after a corpus run:

```bash
uv run snowprove corpus summarize snowprove-runs/corpus/corpus-run.json
```

To persist a machine-readable summary:

```bash
uv run snowprove corpus summarize snowprove-runs/corpus/corpus-run.json \
  --summary-file snowprove-runs/corpus/corpus-summary.json \
  --format json
```

The summary ranks strategies by task wins and mean cumulative reward, then
reports explored-node, logical verifier-request, logical benchmark-request, and
elapsed-time costs. Physical cache misses remain in the JSON artifact but are
not used to rank strategies because the first requester necessarily incurs
them for later strategies.
Each task is classified as positive, neutral, negative, or errored.

Path disagreement means completed strategies selected different action
sequences. Reward disagreement means the best and worst completed rewards
differ by more than `--neutral-threshold`, which defaults to `0.01`. A task is
marked trivial when every completed strategy selects the same path and rewards
remain within that threshold.

When a run uses `--reward-margin`, summaries use at least that value as their
effective neutral threshold so reported winners match the search policy.

## Aggregating Repeated Runs

`corpus repeat` is the normal workflow. To aggregate reports produced
separately, pass two or more compatible run reports explicitly:

```bash
uv run snowprove corpus aggregate \
  snowprove-runs/run-1/corpus-run.json \
  snowprove-runs/run-2/corpus-run.json \
  --aggregate-file snowprove-runs/corpus-aggregate.json
```

Reports must use the same corpus fingerprint, task set, run configuration, and
runtime environment. The aggregate records:

- strategy reward mean, standard deviation, and range
- mean wins, logical benchmark requests, and elapsed time
- tasks whose winning strategies change across runs
- tasks whose positive/neutral/negative classification changes
- strategies that select different action paths across runs
- maximum per-strategy reward standard deviation for each task

This separates stable corpus-level policy differences from noisy task-level
decisions. Path changes on near-neutral tasks indicate that the reward margin
is too small to support a reliable training label.

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
