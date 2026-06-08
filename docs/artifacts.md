# JSON Artifacts

Snowprove JSON output is intended for CI and review tooling. Every artifact has:

- `schema_version`: currently `1`
- `artifact_type`: identifies the payload shape
- `dialect`: selected SQL dialect, or `inputs.dialect` on individual
  verification results

Only `PROVEN_EQUIVALENT` should be treated as safe. `UNKNOWN`, `UNSUPPORTED`,
and `NOT_EQUIVALENT` are not safe rewrite approvals.

## `duckdb_fixture`

Emitted by:

```bash
snowprove fixtures create fixture.duckdb --seed 42 --format json
```

The same JSON is written beside the database by default as
`fixture.duckdb.manifest.json`.

Important fields:

- `spec`: seed, table row counts, and requested distribution controls
- `tables`: row counts, observed statistics, and deterministic content
  fingerprints
- `duckdb_version`: engine version used to generate the fixture
- `database_path`: reusable DuckDB database path

## `duckdb_benchmark`

Emitted by:

```bash
snowprove benchmark original.sql rewritten.sql \
  --setup setup.sql \
  --report-file benchmark.json \
  --format json
```

Important fields:

- `status`: `COMPLETED`, `ERROR`, or `TIMEOUT`
- `environment`: DuckDB, Python, platform, database, thread, warmup,
  repetition, and timeout metadata
- `original` and `rewritten`: per-execution and batch timing samples,
  executions per sample, median, median absolute deviation, range, row count,
  and `EXPLAIN` output
- `speedup`: original median divided by rewritten median
- `timing_confident`: whether the benchmark should be used as a reward signal
- `confidence_reason`: why a completed benchmark was marked low confidence
- `row_counts_match`: diagnostic cardinality comparison

The evaluator materializes every result and alternates original/rewritten
execution order. Row-count equality is not semantic equivalence; benchmark only
after a verifier has approved the pair.

Corpus search steps copy the benchmark medians, speedup, batch sizes, and
confidence into the run report so aggregate inspection does not depend on
external cache files for newly generated reports.

Each search result records `tie_policy`. Corpus runs use `shorter` for
transition rewards and `endpoint` for state rewards.

Corpus run configuration records `reward_model`. Transition mode caches
verified SQL pairs under `benchmark`; state mode caches each distinct SQL text
under `query_benchmark`. State-cache `inputs.measurement_mode` distinguishes an
initial `interleaved_pair` measurement from an `interleaved_anchored`
measurement. Anchored entries also record `anchor_sql` and the applied
`normalization_factor`.

## `verification`

Emitted by:

```bash
snowprove check ... --format json
```

Important fields:

- `status`: verifier result
- `proven`: true only for `PROVEN_EQUIVALENT`
- `rule_name`: rule/backend that produced the result
- `inputs`: original, rewritten, and schema paths
- `assumptions`: trusted assumptions used by the proof
- `counterexample`: optional counterexample text

## `candidate_generation`

Emitted by:

```bash
snowprove candidates generate ... --format json
```

Important fields:

- `original_path`
- `output_dir`
- `generated_count`
- `skipped_count`
- `generated`: candidate file paths and producing rules
- `skipped`: rule results without candidate SQL

## `candidate_verifications`

Emitted by:

```bash
snowprove candidates check ... --format json
```

Important fields:

- `result_count`
- `proven_count`
- `results`: one `verification`-like object per candidate
- `candidate_metadata`: optional metadata from `metadata.json` when
  `--candidates-dir` is used

Candidate metadata is report context only. It does not affect verification.

## `candidate_run`

Emitted by:

```bash
snowprove candidates run ... --format json
snowprove candidates run ... --report-file candidate-run.json
```

Important fields:

- `generation`: same summary shape as `candidate_generation`
- `verification`: same summary shape as `candidate_verifications`

This is the preferred artifact for a candidate-producing CI step.

## `dbt_scan`

Emitted by:

```bash
snowprove dbt scan ... --format json
snowprove dbt scan ... --report-file snowprove-report.json
```

Important fields:

- `model_count`
- `proven_finding_count`
- `summary`: counts by status, rule, and reason
- `results`: model-level findings
- `apply_ready`: whether a proven rewrite can be directly applied
- `apply_blocker`: reason direct apply is unavailable
- `patches`: patch paths when `--write-patches` is used
