# Real Project Evaluation

Before treating Snowprove as public CI tooling, test it on real dbt projects in
advisory mode. The goal is to learn unsupported SQL/Jinja patterns and confirm
that reports are understandable.

## Suggested Projects

- `dbt-labs/jaffle-shop`
- `dbt-labs/jaffle_shop_duckdb`
- `kestra-io/dbt-demo`
- `Snowflake-Labs/getting-started-with-dbt-on-snowflake`
- `fivetran/dbt_shopify`
- one Jinja-heavy dbt project with macros, refs, sources, and compiled SQL

## Batch Evaluation Script

Snowprove includes a helper that clones a curated set of public dbt projects
into `/tmp` and writes reports under `snowprove-runs/`:

```bash
scripts/evaluate_real_projects.sh
```

Useful overrides:

```bash
REFRESH=1 scripts/evaluate_real_projects.sh
REPORT_ROOT="$PWD/snowprove-runs/real-projects/manual" scripts/evaluate_real_projects.sh
RUN_COMPILED=1 scripts/evaluate_real_projects.sh
DBT_PROFILES_DIR="$HOME/.dbt" RUN_COMPILED=1 scripts/evaluate_real_projects.sh
DUCKDB_DBT_COMMAND="uvx --from dbt-duckdb dbt" RUN_COMPILED=1 scripts/evaluate_real_projects.sh
PROJECT_FILTER=duckdb RUN_COMPILED=1 scripts/evaluate_real_projects.sh
```

`RUN_COMPILED=1` requires a working `dbt` command and project profiles. If dbt
dependencies or compilation fail, the script records a skip file and keeps the
raw scan report.

DuckDB projects use a generated temporary `profiles.yml` under the report
directory and default to `uvx --from dbt-duckdb dbt`, so they can compile
without cloud credentials or a global dbt-duckdb installation.

Compare one or more completed run directories:

```bash
uv run scripts/compare_real_project_reports.py \
  --scan-kind compiled \
  snowprove-runs/real-projects/RUN_A \
  snowprove-runs/real-projects/RUN_B

uv run scripts/compare_real_project_reports.py \
  --format json \
  snowprove-runs/real-projects/RUN_A
```

If an individual repository has an unexpected layout or Snowprove rejects it
before producing a report, the script records `raw-skipped.txt` and continues to
the next project.

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

Watch for compiled dbt test SQL under paths such as
`target/compiled/<project>/models/schema.yml/...`. Those files can produce
valid Snowprove findings, but they are dbt-generated tests rather than model
optimization opportunities. Treat them separately from source model findings.

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
