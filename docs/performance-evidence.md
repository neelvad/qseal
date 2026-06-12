# Performance Evidence

Snowprove proves semantic safety; it does not claim performance. This track
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
uv run python scripts/benchmark_proven_candidates.py \
  snowprove-runs/llm-candidates/gitlab-full-verification-final.json \
  snowprove-runs/llm-candidates/gitlab-full \
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

## Next tiers

- **Tier 2 (Snowflake EXPLAIN diffing, roadmap v0.3):** replay project DDL
  into a Snowflake trial account and diff plan trees for proven pairs —
  work-eliminated evidence on the actual target engine without production
  data.
- **Tier 3 (design partner):** the benchmark harness against a real
  warehouse with real distributions.
