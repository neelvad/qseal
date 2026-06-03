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
```

`suggest` proposes the first applicable verified rewrite. `check` verifies a
specific original/rewritten query pair.

Useful options:

```bash
uv run snowprove suggest examples/distinct/original.sql --schema examples/distinct/schema.yml --all
uv run snowprove suggest examples/predicate_pushdown/original.sql --schema examples/distinct/schema.yml --rule predicate_pushdown
uv run snowprove check examples/distinct/original.sql examples/distinct/rewritten.sql --schema examples/distinct/schema.yml --format json
uv run snowprove suggest examples/dbt/distinct.sql --schema examples/dbt/schema.yml
uv run snowprove dbt scan examples/dbt_project
```

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
unknown and unsupported results, including models that contain uncompiled
dbt/Jinja syntax:

```bash
uv run snowprove dbt scan examples/dbt_project --all
uv run snowprove dbt scan examples/dbt_project --diff
uv run snowprove dbt scan examples/dbt_project --write-patches patches/
uv run snowprove dbt scan examples/dbt_project --format json
uv run snowprove dbt scan examples/dbt_project --fail-on findings
uv run snowprove dbt scan examples/dbt_project --use-compiled
uv run snowprove dbt scan examples/dbt_project --compiled-dir examples/dbt_project/target/compiled/snowprove/models
```

`--diff` is read-only. It prints unified diffs for proven rewrites and does not
modify model files.

`--write-patches DIR` writes those read-only unified diffs as `.patch` files.
The patches can be reviewed or applied later with tools such as `git apply`.

Scan reports include project-level summary counts by result status and rewrite
rule. JSON output includes the same data under the `summary` key.

`--fail-on findings` exits nonzero only when Snowprove finds at least one
`PROVEN_EQUIVALENT` rewrite. `UNKNOWN` and `UNSUPPORTED` results do not fail the
command.

`--compiled-dir` lets Snowprove read already-compiled dbt SQL while still using
constraints from the source project's `models/` schema files. Snowprove does not
run `dbt compile` itself.

`--use-compiled` auto-discovers a single compiled SQL directory under
`target/compiled/`. If multiple compiled directories are found, Snowprove asks
for an explicit `--compiled-dir`.

When compiled SQL is scanned, reports and diffs prefer the matching source model
path under `models/` while still showing the compiled SQL path used for parsing.

## Current Scope

Currently modeled:

- direct column projections
- simple direct table sources
- one simple subquery source
- simple `WHERE` predicates with `AND`
- `LEFT JOIN ... ON a.col = b.col`
- table aliases
- `DISTINCT` removal when projected columns are known unique
- predicate pushdown through simple projection subqueries
- unused `LEFT JOIN` elimination when the joined key is known unique
- redundant `IS NOT NULL` filter removal when the column is trusted non-null
- trusted constraints loaded from Snowprove YAML or dbt `schema.yml`
- dbt project scans over `models/**/*.sql`

Explicitly out of scope for now:

- windows and `QUALIFY`
- `ORDER BY` and `LIMIT`
- aggregation and `GROUP BY`
- `OR`, `IN`, `EXISTS`, and subquery predicates
- join reordering
- `INNER JOIN` rewrites
- UDFs
- semi-structured `VARIANT` / `FLATTEN`
- external verifier backends
- Snowflake connections
- dbt manifest parsing and automatic `ref()` resolution

## Project Docs

- [Scope](docs/scope.md): current proof and product boundaries
- [Architecture](docs/architecture.md): package layout and execution flow
- [Roadmap](docs/roadmap.md): planned phases
- [Contributing](CONTRIBUTING.md): local development and rewrite-rule guidance
