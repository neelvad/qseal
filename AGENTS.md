# Snowprove Handoff

This file summarizes the current project state and near-term plan so future
sessions can resume quickly.

## Project Goal

Snowprove is a CLI-first prototype for verified-safe SQL rewrites over a small
Snowflake/dbt subset. The eventual direction is:

1. A user supplies a base SQL query.
2. An untrusted generator, eventually an LLM, proposes an optimized candidate.
3. Snowprove verifies semantic equivalence for supported cases.
4. CI reports proven rewrites, patch files, and verification artifacts.

The current product does not prove performance improvement. It proves semantic
equivalence for supported rewrite patterns under trusted schema assumptions.

## Current Status

The project is a Python/uv CLI package with tests and GitHub CI.

Core commands:

```bash
uv run snowprove suggest query.sql --schema schema.yml
uv run snowprove suggest query.sql --schema schema.yml --all --format json
uv run snowprove check original.sql rewritten.sql --schema schema.yml
uv run snowprove check original.sql rewritten.sql --schema schema.yml --fail-on unproven --format json
uv run snowprove dbt scan .
uv run snowprove dbt scan . --all
uv run snowprove dbt scan . --diff
uv run snowprove dbt scan . --report-file snowprove-report.json
uv run snowprove dbt scan . --write-patches snowprove-patches
uv run snowprove dbt scan . --apply-patches
uv run snowprove dbt scan . --use-compiled
```

Important validation commands:

```bash
UV_CACHE_DIR=.uv-cache uv run pytest
UV_CACHE_DIR=.uv-cache uv run ruff check .
```

Both passed after the latest changes.

## Implemented Capabilities

Supported SQL subset includes:

- direct table sources
- simple subquery sources
- direct column projections
- column projection aliases, for example `user_id AS id`
- simple `WHERE` predicates joined by `AND`
- simple `WHERE EXISTS (SELECT 1 FROM ... WHERE a.col = b.col)`
- `INNER JOIN ... ON a.col = b.col`
- `LEFT JOIN ... ON a.col = b.col`
- qualified Snowflake relation names such as `analytics.public.users`

Trusted constraints:

- Snowprove YAML
- dbt `schema.yml` / `.yaml`
- dbt `unique` and `not_null` column tests

Rewrite rules:

- `remove_redundant_distinct`
- `remove_redundant_not_null_filter`
- `remove_unused_left_join`
- `predicate_pushdown`
- `rewrite_join_distinct_to_exists`

dbt workflows:

- scans `models/**/*.sql`
- reports unsupported Jinja unless compiled SQL is used
- supports `--compiled-dir`
- supports `--use-compiled`
- maps compiled SQL back to source model paths when possible
- refuses direct apply when scan came from compiled SQL
- emits text, JSON, diffs, patch files, and report files
- records patch paths inside JSON reports when `--write-patches` is used
- summarizes repeated unsupported/reason messages

CI/reporting:

- versioned JSON artifacts with `schema_version` and `artifact_type`
- `verification` artifacts include `proven`, `rule_name`, and input paths
- `dbt_scan` artifacts include summaries, apply readiness, blockers, and patch paths
- `dbt scan --fail-on findings`
- `check --fail-on unproven`
- GitHub Actions examples in `docs/github-actions.md`

## Recent Commits

Recent useful commits include:

```text
e81e8d3 Summarize dbt scan reasons
a4c9951 Allow left predicates in join distinct rewrites
80706d3 Support column aliases in projections
6555cf1 Document GitHub Actions workflow
4bb384d Include patch paths in dbt scan reports
90b9afa Harden candidate verification API
39ed5e8 Write dbt scan JSON report files
fdc32f9 Version JSON report artifacts
7fb9173 Rewrite join distinct queries to exists
aef0c7b Support inner joins in SQL parser
```

## Development Style

- Prefer small stacked commits with descriptive messages.
- Keep rewrites conservative.
- Default to `UNKNOWN` or `UNSUPPORTED` instead of guessing.
- Do not trust Snowflake unenforced constraints unless explicitly supplied as
  trusted assumptions.
- Keep LLM generation out of the trusted path; future LLM candidates must pass
  `snowprove check ... --fail-on unproven`.
- Use `rg` for search.
- Use `apply_patch` for manual edits.
- Do not revert user changes.

## Recommended Next Step

Try the tool on real public dbt projects in advisory mode:

```bash
uv run snowprove dbt scan . \
  --all \
  --report-file snowprove-report.json \
  --write-patches snowprove-patches
```

Good first repos:

- `dbt-labs/jaffle-shop`
- `Snowflake-Labs/getting-started-with-dbt-on-snowflake`

For Jinja-heavy projects with working dbt setup:

```bash
dbt compile
uv run snowprove dbt scan . \
  --use-compiled \
  --all \
  --report-file snowprove-report.json \
  --write-patches snowprove-patches
```

Evaluate:

- whether dbt discovery works
- unsupported reason counts
- generated patches
- report JSON shape
- compiled-to-source mapping
- generated SQL readability

Use the unsupported reason distribution to pick the next item-1 hardening task.

## Likely Future Work

Core SQL hardening:

- CTE support
- `SELECT *` handling or clearer refusal
- more alias forms
- simple casts and scalar functions
- better generated SQL formatting
- less full-file rewrite churn
- more real dbt compiled SQL path shapes

Verifier/reporting:

- structured parse-error codes
- richer counterexamples
- eventual external solver adapter, likely QED or SQLSolver

CI/product:

- PR comments or annotations
- SARIF output
- changed-files-only scanning
- optional `snowprove ci dbt .` wrapper if command lines become too long

LLM phase, later:

- add an untrusted candidate-generation command
- run every candidate through `check --fail-on unproven`
- never apply or recommend an LLM rewrite unless Snowprove proves equivalence
