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

## `snowflake_family_benchmark_suite`

Emitted by:

```bash
qseal benchmark-suite snowflake-family snowflake-family-run \
  --report-file suite.json \
  --format json

qseal benchmark-suite snowflake-dbt-demo snowflake-dbt-demo-run \
  --report-file suite.json \
  --format json
```

Important fields:

- `suite_id`: currently `snowflake-family-v1` or `snowflake-dbt-demo-v1`
- `runs`, `modes`, `scales`, `warmups`, `repetitions`, and timeout settings:
  the measurement configuration
- `classification_counts`: counts such as `positive`, `neutral`,
  `neutral_noisy`, `mixed`, or `error`
- `summaries`: one compact row per case/run with wall-clock speedup,
  Snowflake query-history execution speedup, bytes scanned, row-count match,
  timing confidence, classification, notes, and artifact paths
- `results`: the full case spec and embedded `snowflake_benchmark` result for
  each case/run. dbt-demo specs also include trusted dbt assumptions and review
  notes.

The suite also writes each generated `setup.sql`, `original.sql`,
`rewritten.sql`, and per-case `benchmark.json` under the output directory.
Use the top-level suite artifact for product evidence summaries and the
per-case benchmark artifacts for detailed query IDs, plans, and query-history
metadata.

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

## `candidate_evidence`

Emitted by:

```bash
qseal candidates evidence original.sql \
  --candidates-dir candidates/ \
  --schema schema.yml \
  --report-file evidence.json \
  --format json
```

Important fields:

- `candidate_count`, `proven_count`, and `benchmarked_count`
- `verification_counts`: status counts across all candidate verifications
- `benchmark_outcomes`: outcomes for the proven candidates that were
  benchmarked
- `results`: one row per candidate with the embedded verification result,
  candidate metadata, benchmark skip reason for unproven candidates, optional
  benchmark evidence, and a recommendation
- `results[].review_section`: PR-style grouping such as
  `safe_worth_considering`, `safe_no_clear_speedup`, `needs_review`, or
  `rejected_unproven`
- `results[].required_tests`: derived guarding tests for proven candidates
- `results[].review_diff`: unified diff for proven candidates

Only candidates with `PROVEN_EQUIVALENT` verification are benchmarked. The
current benchmark evidence uses deterministic synthetic DuckDB data derived from
the trusted schema constraints. It is ranking evidence, not a semantic proof and
not a Snowflake dollar-savings claim.

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
- `rewrite_chain`: present for `qseal dbt scan --chain`; includes `status`,
  `reason`, `step_count`, `original_sql`, `final_sql`, and per-step
  suggestions with `required_tests`

## `dbt_intake`

Emitted by:

```bash
qseal dbt intake ... --format json
qseal dbt intake ... --report-file qseal-intake.json
```

This is the privacy-preserving companion to `dbt_scan`. It is meant for an
initial design-partner or public-repo fit check when the project owner should
not share source SQL.

The artifact intentionally omits SQL, model names, file paths, diffs, raw
unsupported reasons, and literal accepted values. It keeps only aggregate
fields:

- `redaction`: machine-readable booleans describing the omitted data classes
- `scan_options`: dialect, rule set, compiled SQL mode, and chain mode
- `summary.model_count`, `result_count`, `silent_model_count`
- `summary.proven_model_count`, `proven_finding_count`,
  `apply_ready_model_count`
- `summary.status_counts`, `rule_counts`, `reason_category_counts`,
  `required_test_category_counts`, and `apply_blocker_category_counts`
- `chain_summary`: aggregate rewrite-chain step counts
- `rule_families`: per-rule aggregate observed/proven/apply-ready counts and
  required test categories
