# Real Project Evaluation

Before treating QuerySeal as public CI tooling, test it on real dbt projects in
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

QuerySeal includes a helper that clones a curated set of public dbt projects
into `/tmp` and writes reports under `qseal-runs/`:

```bash
scripts/evaluate_real_projects.sh
```

Useful overrides:

```bash
REFRESH=1 scripts/evaluate_real_projects.sh
REPORT_ROOT="$PWD/qseal-runs/real-projects/manual" scripts/evaluate_real_projects.sh
RUN_COMPILED=1 scripts/evaluate_real_projects.sh
DBT_PROFILES_DIR="$HOME/.dbt" RUN_COMPILED=1 scripts/evaluate_real_projects.sh
DUCKDB_DBT_COMMAND="uvx --from dbt-duckdb dbt" RUN_COMPILED=1 scripts/evaluate_real_projects.sh
PROJECT_FILTER=duckdb RUN_COMPILED=1 scripts/evaluate_real_projects.sh
QSEAL_DBT_SCAN_ARGS="--rule remove_redundant_distinct" scripts/evaluate_real_projects.sh
```

`RUN_COMPILED=1` requires a working `dbt` command and project profiles. If dbt
dependencies or compilation fail, the script records a skip file and keeps the
raw scan report.

DuckDB projects use a generated temporary `profiles.yml` under the report
directory and default to `uvx --from dbt-duckdb dbt`, so they can compile
without cloud credentials or a global dbt-duckdb installation.

Use `QSEAL_DBT_SCAN_ARGS` to compare rule subsets against the default rule set
without checking out an older QuerySeal revision.

## Local Yield Pack

The public demo repos are useful for blocker measurement, but they do not
currently contain many premise-bearing query shapes. For a deterministic scanner
yield regression, use the checked-in dbt-style fixture:

```bash
uv run qseal dbt scan tests/fixtures/dbt_projects/yield_pack --format text
uv run qseal dbt scan tests/fixtures/dbt_projects/yield_pack --chain --format text
```

The one-step scan covers all current default rule families with 12 apply-ready
findings across 12 models. The chain scan reports 13 verified steps because one
model composes redundant `IS NOT NULL` removal with redundant `DISTINCT`
removal. This fixture is a smoke test for supported premise vocabulary and
evidence reporting; it is not a substitute for measuring yield on design-partner
or production dbt projects.

Compare one or more completed run directories:

```bash
uv run scripts/compare_real_project_reports.py \
  --scan-kind compiled \
  qseal-runs/real-projects/RUN_A \
  qseal-runs/real-projects/RUN_B

uv run scripts/compare_real_project_reports.py \
  --format json \
  qseal-runs/real-projects/RUN_A
```

The comparison table includes `SILENT`, the number of scanned models with no
visible scan result in the artifact, and `HIT/M`, proven findings per scanned
model. A high silent count means the scan did not find a proven, unknown, or
unsupported result for many models; inspect the raw `--all` reports and top
reasons before treating it as a parser problem.

If an individual repository has an unexpected layout or QuerySeal rejects it
before producing a report, the script records `raw-skipped.txt` and continues to
the next project.

## Privacy-Preserving Intake

For a private design-partner project, start with an aggregate intake artifact:

```bash
uv run qseal dbt intake . --report-file qseal-intake.json
uv run qseal dbt intake . --use-compiled --report-file qseal-compiled-intake.json
```

`dbt intake` runs the scanner in all-results mode, then strips the fields that
would expose private project details. The JSON artifact omits SQL, model names,
file paths, diffs, raw unsupported reasons, and literal accepted values. It
keeps the funnel metrics needed for a first-fit review: scanned model count,
silent model count, proven finding count, rule counts, status counts, redacted
unsupported reason categories, required dbt test categories, apply-readiness
counts, and rewrite-chain totals.

Use this before asking for a full corpus or source checkout. If the intake
shows useful rule families and acceptable unsupported categories, the next step
is a more detailed scan report under an NDA or in the partner's own CI.

## Static Raw SQL Scan

```bash
uv run qseal dbt scan . \
  --all \
  --report-file qseal-report.json \
  --write-patches qseal-patches
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
uv run qseal dbt scan . \
  --use-compiled \
  --all \
  --report-file qseal-compiled-report.json \
  --write-patches qseal-compiled-patches
```

Review:

- compiled-to-source path mapping
- unsupported reason counts after Jinja is removed
- generated SQL readability
- whether findings are useful even when not apply-ready

QuerySeal scans only compiled SQL files that map back to existing source models
under `models/`. Compiled dbt test SQL under paths such as
`target/compiled/<project>/models/schema.yml/...` and package-only compiled SQL
are ignored so real-project summaries reflect model cleanup suggestions.

## Candidate Pipeline Smoke

For a small query extracted from a real project:

```bash
uv run qseal candidates run model.sql \
  --schema schema.yml \
  --out qseal-candidates \
  --report-file qseal-candidate-run.json
```

If an external/manual/LLM-like producer writes candidates:

```bash
uv run qseal candidates check model.sql \
  --schema schema.yml \
  --candidates-dir qseal-candidates \
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
(`qseal-runs/real-projects/20260610T163428Z`), after the non-null unique
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

2026-06-18 before/after expansion check:

- Baseline command used the pre-expansion rule subset through
  `QSEAL_DBT_SCAN_ARGS`.
- Expanded command used the default rule set, including relationships/FK,
  accepted-values, count-distinct, and group-by rewrites.
- Raw scan over the seven configured public projects: 340 models, 305 visible
  results, 0 proven findings in both runs.
- Compiled scan completed for `dbt-labs-jaffle_shop_duckdb` and
  `kestra-io/dbt-demo` after setting `UV_CACHE_DIR` and `UV_TOOL_DIR` under
  `/tmp`; those 10 compiled models produced 0 proven findings in both runs.

Conclusion: the new premise-driven rules work in targeted fixtures and the
product demo, but this public corpus still does not contain matching dbt
premises/query shapes. Real design-partner projects remain the needed yield
test.

## 2026-06-10 Run: GitLab Analytics (Production-Scale Corpus)

Scanned the sqlfmt mirror of the GitLab Data Team dbt project
(`tconbeer/gitlab-analytics-sqlfmt`, ~2022 snapshot of
`gitlab-data/analytics`; the upstream repo is no longer public). Raw scan,
Snowflake dialect, 2,206 models.

Results: **1 proven finding** (first nonzero on a production corpus), 5
UNKNOWN, 1,733 UNSUPPORTED.

The proven finding is `models/legacy/sheetload/data_team_milestone_capacity.sql`:
a defensive `SELECT DISTINCT` inside a CTE whose projection contains
`milestone_id`, which carries `unique` + `not_null` dbt tests on
`gitlab_dotcom_milestones_xf`. The finding required the full pipeline: static
`ref()` resolution, fragment parsing inside a multi-CTE model, the non-null
unique key premise, and splice-back. A warehouse optimizer cannot perform this
rewrite because the uniqueness is only declared in dbt tests.

Top blockers by reason count:

- 477x projection subset (`Only direct columns, stars, and simple aliased
  scalar projections`): now the largest SQL-side blocker, ahead of Jinja
- 346x Jinja block syntax; ~500x macro expressions (`simple_cte` 126,
  `dbt_audit` 125, `hash_sensitive_columns` 62, `dbt_utils.group_by` 57)
- 51x QUALIFY, 41x non-literal WHERE comparisons, 31x non-SELECT CTEs

The scan also exposed a robustness bug (sqlglot `TokenError` crashing the
whole scan), fixed by catching `SqlglotError` in the parser entry points.

## 2026-06-10 Run: Sandboxed Jinja Rendering

`preprocess_dbt_sql` now renders dbt Jinja in a sandboxed environment with
first-run compile semantics for known builtins (`ref`, `source`, `config`,
`var` with defaults, `is_incremental()` as false). Unknown macros and `var`
without defaults still fall back to the static path and its
unsupported-reason reporting.

GitLab analytics re-scan: proven findings 1 -> 2 (the second is another
defensive `SELECT DISTINCT` backed by `unique` + `not_null` tests on
`bamboohr_headcount_intermediate.unique_key`, in a previously Jinja-blocked
model). Jinja block-syntax blockers dropped 346 -> 141; the unblocked models
now surface SQL-subset blockers instead (QUALIFY visibility rose 16 -> 189).

The two largest remaining levers, by reason count: the projection subset
(478x) and QUALIFY (231x total), both SQL-subset work; then the GitLab-local
`simple_cte`/`dbt_audit` macros (251x), which only compiled SQL can recover.

## 2026-06-10 Run: Projection, QUALIFY, and Fragment-Fallback Coverage

Three coverage changes, re-measured on the GitLab corpus (2,206 models):

- General aliased scalar/window expression projections (was the top blocker
  at 478 models), with subqueries still excluded.
- Opaque `QUALIFY` parsing with per-rule conservative treatment (was 231
  models including CTE-relation references).
- dbt scans fall back to fragment rewrites when the whole query parses but
  proves nothing, since whole-query rules cannot see inside opaque CTE
  bodies.

Alongside: two soundness fixes found during the work. Opaque expression
projections now record referenced relations, closing a hole where unused
LEFT JOIN elimination could prove a rewrite that dropped a join its
projections still referenced (for example `COALESCE(u.name, 'x')`). Rules
also refuse standalone rewrites of queries referencing CTE relations, whose
regenerated SQL would dangle without the defining WITH clause.

Results: UNSUPPORTED dropped 1,730 -> 1,084; 51% of models now parse (21%
this morning). Proven findings hold at 2; UNKNOWN rose 5 -> 25, mostly
join-elimination near-misses. Remaining blockers are GitLab-local macros
(`simple_cte`, `dbt_audit`, ~600 models total, compile-only), non-literal
WHERE comparisons (59), set-operation CTEs (45), and non-table join targets
(37).
