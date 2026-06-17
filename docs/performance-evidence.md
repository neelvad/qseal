# Performance Evidence

QuerySeal proves semantic safety; it does not claim performance. This track
builds the evidence layer that ranks proven rewrites by measured benefit.

## Tier 1: DuckDB micro-benchmarks on synthetic data

`scripts/benchmark_proven_candidates.py` takes a verification report and the
candidate bundles, and for every proven rewrite: extracts the pair's table
schemas (the same attribution machinery the verifiers use), synthesizes
schema-conforming data as pure SQL (`CREATE TABLE ... AS SELECT` over
`range(N)` with hash-based expressions — deterministic, no inserts), and runs
the existing DuckDB benchmark harness on the Snowflake-to-DuckDB transpiled
pair.

Premise fidelity is enforced two ways: constraint columns are always
materialized (trusted unique keys get genuinely unique values, trusted
non-null columns get no NULLs, other columns get ~10% NULLs), and any
measurement where the two sides return different row counts is marked
`suspect` — the pairs are proven equivalent, so a count mismatch can only
mean the synthetic data violated the premises.

```bash
uv run qseal llm benchmark \
  qseal-runs/llm-candidates/gitlab-full-verification-final.json \
  qseal-runs/llm-candidates/gitlab-full \
  --report-file bench.json --rows 100000,1000000

uv run modal run scripts/modal_benchmark.py \
  --report-path ...-final.json --bundles-dir ...gitlab-full \
  --report-file bench.json --shards 40
```

## First sweep (GitLab corpus, 2026-06-12)

282 proven rewrites x two scales (100K and 1M rows), on Modal in minutes:

| Outcome (564 measurements) | Count |
|---|---|
| faster (>= 1.2x) | 14 |
| neutral | 510 |
| slower (<= 0.83x) | 3 |
| failed (timeouts, binder gaps) | 31 |
| error / suspect | 6 / 0 |

Top wins at 1M rows are 1.3-2.2x, concentrated in dedup-removal shapes
(`flaky_tests_latest`, `roles_yaml_latest`, `team_yaml_latest`). The three
measured pessimizations include an LLM candidate that *added* a DISTINCT
(provably equivalent under the unique premise, strictly more work) — proof
that safe and beneficial are different axes, and that the benchmark layer
belongs in the product as a ranking gate.

Honest limits of Tier 1: synthetic distributions are not production
distributions, queries at these scales run in milliseconds where overheads
dominate, and DuckDB's optimizer is not Snowflake's — a rewrite neutral here
may matter on a billed, distributed warehouse and vice versa.

## Evidence tiers

- **Tier 1: DuckDB micro-benchmarks.** Cheap, reproducible local evidence on
  synthetic data. Useful for ranking and regression tests, not Snowflake dollar
  claims.
- **Tier 2: Snowflake EXPLAIN diffing.** Compile-time plan evidence on the
  target engine without loading production data.
- **Tier 3: Snowflake execution benchmarks.** Real warehouse execution evidence,
  currently using scratch synthetic/setup SQL and repeatable family suites.
  Design-partner data distributions are still needed before making
  dollar-savings claims.

## Tier 2: Snowflake EXPLAIN plan diffing (first sweep, 2026-06-12)

`scripts/explain_proven_candidates.py` replays extracted schemas as empty
tables in a trial-account scratch database (`QSEAL_TIER2`) and diffs
`EXPLAIN USING JSON` operator profiles for each proven pair. EXPLAIN is
compile-only: no warehouse runtime, effectively free. Empty tables do not
collapse plans (verified: DISTINCT still produces an Aggregate node).

| Verdict (282 pairs) | Count |
|---|---|
| no_plan_change | 262 |
| work_eliminated (a table scan dropped) | 3 |
| work_added | 4 |
| error (schema/identifier gaps) | 13 |

Findings:

- **Snowflake's compiler normalizes away most generic restructurings.**
  CTE inlining and similar rewrites produce byte-identical plans - e.g. the
  pass-through-CTE eliminations that measured 1.9x on DuckDB (which
  materializes multi-referenced CTEs) are plan-no-ops on Snowflake. The
  DuckDB-faster set and the Snowflake-improved set do not overlap at all.
  Performance value is engine-specific; rank findings per target engine.
- This strengthens the original thesis: rewrites the optimizer can already
  do are compiled away; the durable value is premise-enabled rewrites the
  engine cannot see. The three scan-eliminations are exactly that shape.
- The four work_added pairs (including the added-DISTINCT candidate) are
  the suppress list.
- The 13 errors include the strongest known DISTINCT-removal pairs, blocked
  by schema-attribution gaps in the replayed DDL - attribution is now the
  highest-leverage improvement across verification, benchmarking, and plan
  diffing alike.

Caveat: empty-table plans show compile-time structure only; stats-driven
effects (pruning, join strategies) need loaded data, and execution timings
need Tier 3.

## Tier 3: Snowflake execution benchmarks

The `qseal benchmark` command can now run the same original/rewritten pair on
Snowflake:

```bash
uv run qseal benchmark original.sql rewritten.sql \
  --engine snowflake \
  --setup setup.sql \
  --query-tag qseal-tier3 \
  --repetitions 5 \
  --report-file snowflake-benchmark.json
```

Configuration comes from `QSEAL_SNOWFLAKE_ACCOUNT`,
`QSEAL_SNOWFLAKE_USER`, `QSEAL_SNOWFLAKE_PASSWORD`,
`QSEAL_SNOWFLAKE_WAREHOUSE`, `QSEAL_SNOWFLAKE_DATABASE`, and
`QSEAL_SNOWFLAKE_SCHEMA`; `QSEAL_SNOWFLAKE_ROLE` is optional. The harness
uses the configured scratch database/schema, disables the session result
cache, alternates original and rewritten executions, captures Snowflake query
IDs, and records query-history metadata such as bytes scanned and
compilation/execution timing when available.

This is the first step toward real warehouse evidence. Synthetic setup SQL is
enough to learn which rewrite classes survive Snowflake compiler
normalization; copied or sampled project data is still needed before making
dollar-savings claims.

For repeatable family-level evidence, use the Snowflake suite runner:

```bash
uv run qseal benchmark-suite snowflake-family snowflake-family-run \
  --scale 1000000 \
  --mode aggregate \
  --runs 1 \
  --warmups 1 \
  --repetitions 3
```

The suite writes generated `setup.sql`, `original.sql`, `rewritten.sql`, one
per-case `benchmark.json`, and a top-level
`snowflake-family-suite.json`. It covers redundant `DISTINCT`, redundant
`IS NOT NULL`, unused `LEFT JOIN`, `JOIN DISTINCT` to `EXISTS`, and predicate
pushdown.

Two small 2026-06-17 runs at 1M users and 2M orders where applicable showed
why the suite records evidence scope. Aggregate queries can expose optimizer
and metadata effects, while bounded materialized-output queries are a more
conservative check that Snowflake still has to return rows.

Aggregate mode:

| Family | Classification | Wall speedup | Snowflake execution speedup | Notes |
|---|---:|---:|---:|---|
| redundant `DISTINCT` | positive | 7.888x | 140.000x | Rewritten aggregate was metadata-answerable; aggregate-query evidence only. |
| redundant `IS NOT NULL` | neutral/noisy | 1.155x | 1.000x | Both sides looked metadata-only or near-metadata-only. |
| unused `LEFT JOIN` | positive | 6.586x | 161.000x | Rewritten aggregate was metadata-answerable; aggregate-query evidence only. |
| `JOIN DISTINCT` to `EXISTS` | positive | 1.542x | 1.479x | Both sides scanned the same bytes; rewritten shape executed faster. |
| predicate pushdown | positive | 1.534x | 1.067x | Same bytes scanned; a single run is not enough to call this durable. |

Bounded materialized-output mode:

| Family | Classification | Wall speedup | Snowflake execution speedup | Notes |
|---|---:|---:|---:|---|
| redundant `DISTINCT` | mixed | 0.683x | 1.692x | Wall-clock and query-history execution medians disagreed. |
| redundant `IS NOT NULL` | negative | 0.916x | 0.917x | Same bytes scanned; no useful win. |
| unused `LEFT JOIN` | positive | 1.132x | 2.100x | Bytes scanned fell from 21.2 MB to 12.5 MB. |
| `JOIN DISTINCT` to `EXISTS` | mixed | 0.844x | 1.285x | Wall-clock and query-history execution medians disagreed. |
| predicate pushdown | neutral | 0.974x | 0.944x | Same bytes scanned; Snowflake appears to normalize the shape. |

This is enough to support the narrower product thesis: generic rewrites are
often already handled by Snowflake or produce scope-specific wins, while
premise-enabled rewrites can still remove work because the optimizer cannot
safely infer dbt tests as trusted execution facts. Treat aggregate-only wins as
candidate signals, not dollar-savings claims, until they survive a query shape
that matches the production workload.
