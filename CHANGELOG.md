# Changelog

## 0.1.0 - Unreleased

- Add a CLI-first prototype for verified-safe SQL rewrites over a constrained
  Snowflake and DuckDB SQL subset.
- Add dbt scanner workflows: `dbt scan`, `dbt intake`, compiled-SQL scanning,
  changed-file scanning, markdown/JSON/text reports, patch files, and
  composition-chain evidence.
- Add conservative premise-backed rewrite rules for redundant `DISTINCT`,
  redundant `IS NOT NULL`, unused `LEFT JOIN`, FK-backed unused `INNER JOIN`,
  `JOIN DISTINCT` to `EXISTS`, redundant `COUNT(DISTINCT)`, accepted-values
  filters, accepted-values `CASE`, unique-key `GROUP BY` collapse, and
  predicate pushdown through simple projection subqueries.
- Add dbt premise ingestion for `unique`, `not_null`, `relationships`,
  `accepted_values`, and `dbt_utils.unique_combination_of_columns`.
- Add candidate verification/evidence workflows for generated or manual SQL
  candidates, with unproven candidates rejected before benchmarking.
- Add repeatable DuckDB benchmark and fixture workflows, plus Snowflake
  benchmark-suite commands for target-engine evidence.
- Add the rewrite-policy experiment surface: structured rewrite actions,
  verified environment steps, corpus runs, trajectory export, search baselines,
  and baseline/ranker policy evaluation.
- Add optional external verifier adapter spikes for SQLSolver, QED, and VeriEQL.
  VeriEQL remains documented as research/evaluation-only and is not bundled.
- Add GitHub CI for tests, Ruff, package build, and installed-wheel smoke tests.
- Remove dormant GitHub Action metadata from the public-v0 surface; CI examples
  install and run the CLI directly.
