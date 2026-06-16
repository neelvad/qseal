# JSON Artifacts

QuerySeal JSON output is intended for CI and review tooling. Every artifact has:

- `schema_version`: currently `1`
- `artifact_type`: identifies the payload shape
- `dialect`: selected SQL dialect, or `inputs.dialect` on individual
  verification results

Only certified approvals should be treated as safe. For compatibility, safe
approvals still use `status: PROVEN_EQUIVALENT`, but consumers should also read
`safety_claim`: builtin verifier approvals report `VERIFIED_BY_RULE`, while
external solver approvals can report `SOLVER_PROVEN_EQUIVALENT`. `UNKNOWN`,
`UNSUPPORTED`, and `NOT_EQUIVALENT` are not safe rewrite approvals.

## `duckdb_fixture`

Emitted by:

```bash
qseal fixtures create fixture.duckdb --seed 42 --format json
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
qseal benchmark original.sql rewritten.sql \
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

## `snowflake_benchmark`

Emitted by:

```bash
qseal benchmark original.sql rewritten.sql \
  --engine snowflake \
  --setup setup.sql \
  --query-tag qseal-tier3 \
  --report-file benchmark.json \
  --format json
```

Required environment variables are `QSEAL_SNOWFLAKE_ACCOUNT`,
`QSEAL_SNOWFLAKE_USER`, `QSEAL_SNOWFLAKE_PASSWORD`,
`QSEAL_SNOWFLAKE_WAREHOUSE`, `QSEAL_SNOWFLAKE_DATABASE`, and
`QSEAL_SNOWFLAKE_SCHEMA`. `QSEAL_SNOWFLAKE_ROLE` and
`QSEAL_SNOWFLAKE_QUERY_TAG` are optional.

Important Snowflake-specific fields:

- `environment`: account, user, role, warehouse, database, schema, connector
  version, query tag, Python, platform, warmup, repetition, and timeout
  metadata. Passwords are never written to artifacts.
- `original.query_ids` and `rewritten.query_ids`: Snowflake query IDs for
  measured samples.
- `bytes_scanned`, `compilation_time_ms`, `execution_time_ms`, and
  `total_elapsed_time_ms`: per-sample query-history metadata when available.

Snowflake benchmarking disables the result cache for the session, applies the
query tag, alternates original/rewritten execution order, and requires both
queries to parse as SELECT-style statements. Optional setup SQL is executed
before warmups and measurements, so it should target a scratch schema.

Corpus search steps copy the benchmark medians, speedup, batch sizes, and
confidence into the run report so aggregate inspection does not depend on
external cache files for newly generated reports.

Each search result records `tie_policy`. Corpus runs use `shorter` for
transition rewards and `endpoint` for state rewards.

Aggregate reports include both raw reward-class-change counts and
uncertainty-adjusted task classifications. `uncertainty_adjusted_reward_class`
is `uncertain` when repeated rewards overlap the neutral threshold inside the
recorded `uncertainty_band`; `uncertainty_reason` explains the classification.

Corpus run configuration records `reward_model`. Transition mode caches
verified SQL pairs under `benchmark`; state mode caches each distinct SQL text
under `query_benchmark`. State-cache `inputs.measurement_mode` distinguishes an
initial `interleaved_pair` measurement from an `interleaved_anchored`
measurement. Anchored entries also record `anchor_sql` and the applied
`normalization_factor`.

## `verification`

Emitted by:

```bash
qseal check ... --format json
```

Important fields:

- `status`: verifier result
- `proven`: true only for `PROVEN_EQUIVALENT`
- `safety_claim`: `VERIFIED_BY_RULE`, `SOLVER_PROVEN_EQUIVALENT`, or another
  explicit claim describing the trust basis
- `verification_method`: backend/method such as `builtin_rule_replay` or
  `sqlsolver`
- `rule_name`: rule/backend that produced the result
- `inputs`: original, rewritten, and schema paths
- `assumptions`: trusted assumptions used by the proof
- `counterexample`: optional counterexample text

## `candidate_generation`

Emitted by:

```bash
qseal candidates generate ... --format json
```

Important fields:

- `original_path`
- `output_dir`
- `generated_count`
- `skipped_count`
- `generated`: candidate file paths and producing rules
- `skipped`: rule results without candidate SQL
- `required_tests`: guard tests implied by each constraint-dependent rewrite

## `candidate_verifications`

Emitted by:

```bash
qseal candidates check ... --format json
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
qseal candidates run ... --format json
qseal candidates run ... --report-file candidate-run.json
```

Important fields:

- `generation`: same summary shape as `candidate_generation`
- `verification`: same summary shape as `candidate_verifications`

This is the preferred artifact for a candidate-producing CI step.

## `dbt_scan`

Emitted by:

```bash
qseal dbt scan ... --format json
qseal dbt scan ... --report-file qseal-report.json
```

Important fields:

- `model_count`
- `proven_finding_count`
- `summary`: counts by status, rule, and reason
- `results`: model-level findings
- `apply_ready`: whether a proven rewrite can be directly applied
- `apply_blocker`: reason direct apply is unavailable
- `patches`: patch paths when `--write-patches` is used
