# Scope

Snowprove is intentionally conservative. A query pair is only proven equivalent
when the parser, rewrite rule, and verifier all support the relevant SQL shape.

## Result Statuses

- `PROVEN_EQUIVALENT`: Snowprove proved the rewrite safe under the displayed
  assumptions.
- `NOT_EQUIVALENT`: Snowprove found a rule-specific reason the rewrite can
  change results.
- `UNKNOWN`: the SQL parsed, but no verifier rule could prove or disprove the
  pair.
- `UNSUPPORTED`: the SQL uses syntax or semantics outside the modeled subset.

## Trusted Assumptions

Constraints are explicit inputs. For example:

```yaml
tables:
  dim_users:
    unique:
      - [user_id]
```

Snowprove treats this YAML as trusted. It does not currently inspect Snowflake
or production data to validate that the constraint is true.

Snowprove can also load dbt-style `schema.yml` files with `--schema-format dbt`.
Currently supported dbt tests:

- column `unique` -> trusted single-column unique key
- column `not_null` -> trusted `nullable: false`

These dbt tests are still treated as assumptions. Snowprove does not run dbt
tests or verify that they passed.

## Supported Rewrite Rules

### `remove_redundant_distinct`

Removes `DISTINCT` when the projected columns contain a trusted unique key.

### `predicate_pushdown`

Pushes an outer filter into a simple projection subquery when the filtered
columns are projected unchanged by the subquery.

### `remove_unused_left_join`

Removes an unused `LEFT JOIN` when:

- the joined relation is not projected
- the joined relation is not filtered outside the join condition
- the joined table's join key is trusted unique

This avoids the common failure mode where a supposedly unused join duplicates
rows because the right side is not actually unique.

### `remove_redundant_not_null_filter`

Removes `IS NOT NULL` predicates when the filtered column is trusted non-null.
This currently applies only to direct table queries.

## Non-Goals

Snowprove does not prove that a query is faster. Runtime depends on Snowflake
optimizer decisions, micro-partitions, clustering, data shape, warehouse size,
caching, and concurrency. Performance validation should be a separate empirical
step.

Snowprove also does not attempt full Snowflake SQL equivalence. The current
subset is meant to be small enough to audit.

## dbt Project Scans

`snowprove dbt scan` discovers SQL files under `models/**/*.sql` and dbt schema
files under `models/**/*.yml` and `models/**/*.yaml`.

Default scan output reports only proven rewrite findings. `--all` includes
unknown and unsupported results.

`--diff` prints unified diffs for proven rewrites with generated SQL. It is
read-only and does not modify project files.

`--fail-on findings` exits nonzero only when at least one proven rewrite finding
exists. Unsupported SQL, unknown equivalence, missing constraints, and uncompiled
dbt/Jinja are not treated as failures under this policy.

Snowprove does not currently compile dbt projects or resolve `ref()` calls. A
model containing dbt/Jinja syntax is reported as `UNSUPPORTED` when `--all` is
used.

Use `--compiled-dir` to scan already-compiled dbt SQL. Schema constraints are
still loaded from the source dbt project's `models/` YAML files.
