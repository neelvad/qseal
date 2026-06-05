# Real Project Evaluation

Before treating Snowprove as public CI tooling, test it on real dbt projects in
advisory mode. The goal is to learn unsupported SQL/Jinja patterns and confirm
that reports are understandable.

## Suggested Projects

- `dbt-labs/jaffle-shop`
- `Snowflake-Labs/getting-started-with-dbt-on-snowflake`
- one Jinja-heavy dbt project with macros, refs, sources, and compiled SQL

## Static Raw SQL Scan

```bash
uv run snowprove dbt scan . \
  --all \
  --report-file snowprove-report.json \
  --write-patches snowprove-patches
```

Review:

- unsupported reason counts
- generated patch readability
- whether raw `ref()` and `source()` preprocessing helped
- whether any findings are apply-ready

## Compiled SQL Scan

For Jinja-heavy projects, compile first:

```bash
dbt compile
uv run snowprove dbt scan . \
  --use-compiled \
  --all \
  --report-file snowprove-compiled-report.json \
  --write-patches snowprove-compiled-patches
```

Review:

- compiled-to-source path mapping
- unsupported reason counts after Jinja is removed
- generated SQL readability
- whether findings are useful even when not apply-ready

## Candidate Pipeline Smoke

For a small query extracted from a real project:

```bash
uv run snowprove candidates run model.sql \
  --schema schema.yml \
  --out snowprove-candidates \
  --report-file snowprove-candidate-run.json
```

If an external/manual/LLM-like producer writes candidates:

```bash
uv run snowprove candidates check model.sql \
  --schema schema.yml \
  --candidates-dir snowprove-candidates \
  --format json \
  --fail-on unproven
```

## Release Gate

Before public release, capture:

- at least two real-project scan reports
- top unsupported SQL/Jinja reasons
- at least one compiled SQL scan
- one candidate bundle check using `metadata.json`
- no known false `PROVEN_EQUIVALENT` result
