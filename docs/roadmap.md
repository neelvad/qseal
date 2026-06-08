# Roadmap

This roadmap is intentionally modest. Snowprove should become useful by staying
conservative, not by pretending to verify all Snowflake SQL.

## v0.1: Local CLI Core

- CLI commands: `suggest` and `check`
- YAML constraint loading
- structured text and JSON output
- hand-written rewrite registry
- redundant `DISTINCT` removal
- predicate pushdown through simple projection subqueries
- unused `LEFT JOIN` elimination
- redundant `IS NOT NULL` filter removal

## v0.2: dbt Constraint Ingestion

- read dbt-style `schema.yml` column tests
- map `unique` tests to trusted unique constraints
- map `not_null` tests to trusted nullability constraints
- document which dbt tests are treated as proof assumptions
- scan dbt model SQL files directly
- scan already-compiled dbt SQL via `--compiled-dir`
- auto-discover compiled SQL with `--use-compiled`
- map compiled SQL findings back to source model paths
- future: invoke `dbt compile` directly

## v0.3: Snowflake Explain Integration

- connect with read-only Snowflake credentials
- run `EXPLAIN`/plan collection for original and rewritten SQL
- report structural plan differences
- keep semantic proof separate from performance observations

## v0.4: CI and PR Workflows

- JSON reports suitable for CI consumption
- unified diff output for reviewable rewrite suggestions
- patch file output for reviewable rewrite suggestions
- opt-in patch application for verified dbt rewrites
- nonzero exit mode for proven rewrite findings
- GitHub Actions report artifact examples
- dbt model scanning experiments

## Later Research Tracks

- bounded counterexample generation
- SMT-backed verification experiments
- adapters for SQLSolver, QED, or related SQL-equivalence tools
- Lean/Coq proofs for the internal rewrite rules

## DuckDB Rewrite-Policy Research

This track uses DuckDB as a reproducible local execution engine while keeping
semantic equivalence and performance measurement separate.

1. Explicit DuckDB dialect propagation through parsing, verification, and
   artifacts.
2. Repeated DuckDB benchmarks with warmups, plans, timeouts, and version data.
3. Seeded query and database fixtures with varied sizes and distributions.
4. Structured rewrite matches that define a finite action space.
5. A framework-neutral environment returning solver status, benchmark results,
   reward, and termination state.
6. Content-addressed caches and JSONL or Parquet trajectory artifacts.
7. Fixed-order, random, greedy, beam-search, exhaustive-search, forced baseline
   policy, and abstaining baseline policy search strategies.
8. A small learned ranking or rule-selection policy beyond the feature-mean
   baseline.
9. SFT and verifier-guided RL for SQL generation only after structured-policy
   experiments demonstrate useful generalization.
