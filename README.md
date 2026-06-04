# snowprove

Verified-safe SQL rewrites for a constrained Snowflake SQL subset.

Snowprove is an early CLI-first project. The goal is narrow: prove that small,
hand-written SQL rewrite rules are semantically safe under explicit schema
constraints, then leave performance validation to Snowflake `EXPLAIN` or
benchmarks later.

It does **not** claim that a rewrite is always faster. It claims that a supported
rewrite returns the same rows under the declared assumptions.

## Install

```bash
uv sync
```

## Commands

```bash
uv run snowprove suggest examples/distinct/original.sql --schema examples/distinct/schema.yml
uv run snowprove check examples/distinct/original.sql examples/distinct/rewritten.sql --schema examples/distinct/schema.yml
uv run snowprove candidates check examples/distinct/original.sql candidates/*.sql --schema examples/distinct/schema.yml
```

`suggest` proposes the first applicable verified rewrite. `check` verifies a
specific original/rewritten query pair. `candidates check` verifies multiple
generated candidate rewrites against one original query.

Useful options:

```bash
uv run snowprove suggest examples/distinct/original.sql --schema examples/distinct/schema.yml --all
uv run snowprove suggest examples/predicate_pushdown/original.sql --schema examples/distinct/schema.yml --rule predicate_pushdown
uv run snowprove check examples/distinct/original.sql examples/distinct/rewritten.sql --schema examples/distinct/schema.yml --format json
uv run snowprove check examples/distinct/original.sql examples/distinct/rewritten.sql --schema examples/distinct/schema.yml --fail-on unproven
uv run snowprove check examples/distinct/original.sql examples/distinct/rewritten.sql --schema examples/distinct/schema.yml --verifier builtin
uv run snowprove check examples/distinct/original.sql examples/distinct/rewritten.sql --schema examples/distinct/schema.yml --verifier external --solver-command qed
uv run snowprove candidates check original.sql candidates/*.sql --schema schema.yml --format json
uv run snowprove candidates check original.sql candidates/*.sql --schema schema.yml --fail-on unproven
uv run snowprove suggest examples/dbt/distinct.sql --schema examples/dbt/schema.yml
uv run snowprove dbt scan examples/dbt_project
```

`check --fail-on unproven` exits nonzero unless Snowprove proves the query pair
equivalent. This is the intended contract for future untrusted candidate
generators, including LLM-generated rewrites.

`candidates check` is the batch form of the same contract: it loads the original
query once, verifies each candidate SQL file independently, and reports only
`PROVEN_EQUIVALENT` candidates as safe. The current verifier backend is
`builtin`, which wraps Snowprove's internal rule-based verifier. `external` is a
stubbed backend for future QED/SQLSolver integration and currently reports
`UNSUPPORTED` instead of executing a solver.

Solver adapter compatibility cases live under
`tests/fixtures/solver_compat/`. They define the small query-pair suite that new
QED/SQLSolver adapters should pass before being exposed as trusted backends.

For CI examples, see [docs/github-actions.md](docs/github-actions.md).

## Examples

### Redundant DISTINCT Removal

Input:

```sql
SELECT DISTINCT user_id
FROM users;
```

Schema contract:

```yaml
tables:
  users:
    unique:
      - [user_id]
```

Run:

```bash
uv run snowprove suggest examples/distinct/original.sql --schema examples/distinct/schema.yml
```

Result:

```text
Result: PROVEN_EQUIVALENT
Rewrite: remove_redundant_distinct
```

### Predicate Pushdown

Input:

```sql
SELECT user_id, revenue
FROM (
  SELECT user_id, revenue
  FROM orders
) x
WHERE revenue > 0;
```

Run:

```bash
uv run snowprove suggest examples/predicate_pushdown/original.sql --schema examples/distinct/schema.yml
```

Result:

```text
Result: PROVEN_EQUIVALENT
Rewrite: predicate_pushdown
```

### Unused LEFT JOIN Elimination

Input:

```sql
SELECT f.user_id, f.revenue
FROM fact_orders f
LEFT JOIN dim_users u ON f.user_id = u.user_id;
```

Schema contract:

```yaml
tables:
  dim_users:
    unique:
      - [user_id]
```

Run:

```bash
uv run snowprove suggest examples/join_elimination/original.sql --schema examples/join_elimination/schema.yml
```

Result:

```text
Result: PROVEN_EQUIVALENT
Rewrite: remove_unused_left_join
```

### dbt Schema Constraints

Snowprove can read dbt-style column tests as trusted assumptions:

```yaml
version: 2

models:
  - name: dim_users
    columns:
      - name: user_id
        tests:
          - unique
          - not_null
```

Run:

```bash
uv run snowprove suggest examples/dbt/distinct.sql --schema examples/dbt/schema.yml
```

The `unique` test becomes a trusted unique-key constraint. The `not_null` test
becomes trusted `nullable: false` metadata.

### Redundant NOT NULL Filter Removal

When a column is trusted non-null, Snowprove can remove an `IS NOT NULL` filter:

```sql
SELECT user_id
FROM dim_users
WHERE user_id IS NOT NULL;
```

Run:

```bash
uv run snowprove suggest examples/dbt/not_null.sql --schema examples/dbt/schema.yml
```

Result:

```text
Result: PROVEN_EQUIVALENT
Rewrite: remove_redundant_not_null_filter
```

### dbt Project Scan

Snowprove can scan dbt model SQL files under a project's `models/` directory:

```bash
uv run snowprove dbt scan examples/dbt_project
```

Default scan output only reports proven rewrite findings. Use `--all` to include
unknown and unsupported results. Raw dbt scans statically resolve simple
`{{ ref('model') }}` and `{{ source('name', 'table') }}` relation references,
but other dbt/Jinja expressions still require compiled SQL:

```bash
uv run snowprove dbt scan examples/dbt_project --all
uv run snowprove dbt scan examples/dbt_project --diff
uv run snowprove dbt scan examples/dbt_project --write-patches patches/
uv run snowprove dbt scan examples/dbt_project --apply-patches
uv run snowprove dbt scan examples/dbt_project --format json
uv run snowprove dbt scan examples/dbt_project --report-file snowprove-report.json
uv run snowprove dbt scan examples/dbt_project --fail-on findings
uv run snowprove dbt scan examples/dbt_project --use-compiled
uv run snowprove dbt scan examples/dbt_project --compiled-dir examples/dbt_project/target/compiled/snowprove/models
```

`--diff` is read-only. It prints unified diffs for proven rewrites and does not
modify model files.

`--write-patches DIR` writes those read-only unified diffs as `.patch` files.
The patches can be reviewed or applied later with tools such as `git apply`.
Patch file paths preserve the model path and append the rewrite rule name, for
example `patches/models/dim_users.sql.remove_redundant_distinct.patch`.

`--apply-patches` applies proven rewrites directly to model SQL files. It is
explicitly opt-in and refuses to apply when Snowprove scanned compiled SQL or
statically preprocessed dbt/Jinja relation references, or when the source file no
longer exactly matches the verified original SQL.
Scan reports show `Apply ready: yes` or `Apply ready: no` for proven findings so
the direct-apply path is visible before running a mutating command.

Scan reports include project-level summary counts by result status and rewrite
rule. JSON output includes the same data under the `summary` key.

`--report-file PATH` writes the same versioned JSON scan artifact to disk while
leaving terminal output in the selected format. This is the preferred CI artifact
path when humans still want text output in logs. When combined with
`--write-patches DIR`, the report includes the generated patch file paths.

`--fail-on findings` exits nonzero only when Snowprove finds at least one
`PROVEN_EQUIVALENT` rewrite. `UNKNOWN` and `UNSUPPORTED` results do not fail the
command.

`--compiled-dir` lets Snowprove read already-compiled dbt SQL while still using
constraints from the source project's `models/` schema files. Snowprove does not
run `dbt compile` itself.

`--use-compiled` auto-discovers a single compiled SQL directory under
`target/compiled/`. If `dbt_project.yml` declares a project name, Snowprove
prefers that local compiled project over compiled package directories. If
multiple compiled directories remain, Snowprove asks for an explicit
`--compiled-dir`.

When compiled SQL is scanned, reports and diffs prefer the matching source model
path under `models/` while still showing the compiled SQL path used for parsing.
Compiled findings are useful for review, but are not directly apply-ready because
the verified SQL is not the source model text.

## Current Scope

Currently modeled:

- direct column projections, star projections, and simple aliased scalar projections
- simple direct table sources
- one simple subquery source
- simple non-recursive CTE pass-through chains, such as `WITH x AS (...) SELECT * FROM x`
- simple `WHERE` predicates with `AND`
- `INNER JOIN ... ON a.col = b.col`
- `LEFT JOIN ... ON a.col = b.col`
- simple `WHERE EXISTS (SELECT 1 FROM ... WHERE a.col = b.col)` predicates
- table aliases
- `DISTINCT` removal when projected columns are known unique
- predicate pushdown through simple projection subqueries
- `JOIN` + `DISTINCT` rewrites to `EXISTS` for left-relation projections
- unused `LEFT JOIN` elimination when the joined key is known unique
- redundant `IS NOT NULL` filter removal when the column is trusted non-null
- trusted constraints loaded from Snowprove YAML or dbt `schema.yml`
- dbt project scans over `models/**/*.sql`

Explicitly out of scope for now:

- windows and `QUALIFY`
- `ORDER BY` and `LIMIT`
- aggregation and `GROUP BY`
- aggregate projection expressions
- `OR`, `IN`, and general subquery predicates
- join reordering
- general `INNER JOIN` rewrites beyond the narrow `EXISTS` pattern
- recursive CTEs and complex CTE references
- UDFs
- semi-structured `VARIANT` / `FLATTEN`
- external verifier backend implementations
- Snowflake connections
- dbt manifest parsing and general macro evaluation

## Project Docs

- [Scope](docs/scope.md): current proof and product boundaries
- [Architecture](docs/architecture.md): package layout and execution flow
- [Roadmap](docs/roadmap.md): planned phases
- [Contributing](CONTRIBUTING.md): local development and rewrite-rule guidance
