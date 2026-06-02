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
- future: compile dbt/Jinja before scanning

## v0.3: Snowflake Explain Integration

- connect with read-only Snowflake credentials
- run `EXPLAIN`/plan collection for original and rewritten SQL
- report structural plan differences
- keep semantic proof separate from performance observations

## v0.4: CI and PR Workflows

- JSON reports suitable for CI consumption
- unified diff output for reviewable rewrite suggestions
- nonzero exit mode for proven rewrite findings
- GitHub comment/report examples
- dbt model scanning experiments

## Later Research Tracks

- bounded counterexample generation
- SMT-backed verification experiments
- adapters for SQLSolver, QED, or related SQL-equivalence tools
- Lean/Coq proofs for the internal rewrite rules
