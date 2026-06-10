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

Snowprove scans only compiled SQL files that map back to existing source models
under `models/`. Compiled dbt test SQL under paths such as
`target/compiled/<project>/models/schema.yml/...` and package-only compiled SQL
are ignored so real-project summaries reflect model optimization opportunities.

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

## 2026-06-10 Run: Fragment Rewriting Baseline

Full refresh run over all seven projects
(`snowprove-runs/real-projects/20260610T163428Z`), after the non-null unique
key soundness fix and fragment (subtree) rewriting landed.

Findings: 350 models scanned, 0 proven rewrites. The public demo corpora are
clean; the zero is a true zero, not a parse failure.

Funnel measurement over the raw model SQL of all cloned projects:

- 340 raw models total
- 287 (84%) blocked by dbt/Jinja macros before SQL parsing; only compiled SQL
  can recover these (the largest project, `fivetran/dbt_shopify` with 264
  models, is entirely macro-blocked and needs a warehouse profile to compile)
- 53 models parse after Jinja preprocessing
- 23 of those parse as whole queries; 30 fail whole-query parsing
- 25 of the 30 failures now expose at least one scannable fragment, so 48/53
  post-Jinja models (91%) are at least partially scannable, up from 23/53
  (43%) before fragment rewriting

Implications:

- Verification coverage is no longer the binding constraint on these demo
  projects; model cleanliness is. Yield must be validated on production dbt
  repositories with defensive `DISTINCT` / `IS NOT NULL` habits.
- The next coverage lever is compiled SQL for macro-heavy projects, which
  requires warehouse profiles (or dbt-duckdb-compatible packages).
