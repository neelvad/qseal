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

## JSON Artifacts

JSON output includes a top-level `schema_version` and `artifact_type`. Current
artifact types are:

- `suggestion`
- `suggestions`
- `verification`
- `candidate_verifications`
- `dbt_scan`

The `verification` artifact also includes:

- `proven`: boolean shortcut for `status == PROVEN_EQUIVALENT`
- `rule_name`: verifier rule that proved or disproved the pair, when available
- `inputs`: original, rewritten, schema path, and schema format metadata

Use `snowprove check ... --fail-on unproven` to exit nonzero unless the query
pair is proven equivalent.

`candidate_verifications` is the batch artifact emitted by
`snowprove candidates check`. It contains one verification result per candidate
SQL file and a `proven_count` summary.

## Verifier Backends

`snowprove check` and `snowprove candidates check` route verification through a
backend interface. `builtin` uses Snowprove's internal parser and rule-specific
equivalence checks. `external` is a stub for future QED/SQLSolver integration;
it accepts `--solver-command` metadata but returns `UNSUPPORTED` instead of
executing a solver.

The external adapter contract is represented by `ExternalSolverRequest`, which
contains original SQL, rewritten SQL, trusted constraints, solver command
metadata, and an optional timeout. Compatibility fixtures under
`tests/fixtures/solver_compat/` define the initial query pairs that future solver
adapters should handle.

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

### `rewrite_join_distinct_to_exists`

Rewrites a narrow `SELECT DISTINCT ... INNER JOIN ...` pattern to `WHERE EXISTS`
when projected columns all come from the left relation and the join is only used
to require at least one matching row. This avoids join row multiplication before
deduplication.

## Non-Goals

Snowprove does not prove that a query is faster. Runtime depends on Snowflake
optimizer decisions, micro-partitions, clustering, data shape, warehouse size,
caching, and concurrency. Performance validation should be a separate empirical
step.

Snowprove also does not attempt full Snowflake SQL equivalence. The current
subset is meant to be small enough to audit.

## Supported SQL Shapes

The current parser models direct table sources, one simple subquery source,
direct column projections, star projections, simple aliased scalar projections,
simple `WHERE` predicates joined by `AND`, simple `EXISTS` predicates,
`INNER JOIN`, and `LEFT JOIN`.

It also resolves narrow non-recursive CTE shapes that commonly appear in dbt
models:

- `SELECT * FROM cte_name` can forward to the referenced CTE body.
- `FROM cte_name` can forward through a CTE body only when that CTE is a
  `SELECT *` pass-through over one direct table or another pass-through CTE.

Complex CTEs remain unsupported when their alias is referenced as a source.
That includes aggregating CTEs, filtering CTEs, joining CTEs, recursive CTEs,
and CTEs that project expressions.

## dbt Project Scans

`snowprove dbt scan` discovers SQL files under `models/**/*.sql` and dbt schema
files under `models/**/*.yml` and `models/**/*.yaml`.

Compiled Snowflake SQL can use fully qualified relation names such as
`database.schema.model_name`. Snowprove preserves those qualified names in
generated rewrites while matching dbt constraints by the unqualified model name.

Default scan output reports only proven rewrite findings. `--all` includes
unknown and unsupported results.

Raw dbt scans statically resolve simple `{{ ref('model') }}` and
`{{ source('name', 'table') }}` relation references. Snowprove does not evaluate
arbitrary Jinja, macros, or dbt adapter helpers; those models are reported as
unsupported with a macro-specific reason unless compiled SQL is supplied.

Scan reports include summary counts for visible results:

- number of scanned models
- number of proven rewrite findings
- counts by result status
- counts by rewrite rule
- counts by repeated reason, useful for prioritizing unsupported SQL shapes

`--report-file PATH` writes a versioned JSON `dbt_scan` artifact to disk. This
can be used with text output, diff output, or JSON stdout. When used with
`--write-patches DIR`, the artifact includes patch paths on the matching scan
results.

For proven findings, scan reports also show whether the finding is apply-ready for
`--apply-patches`. Compiled SQL findings are not apply-ready because the verified
SQL is not the source model text. Findings from statically preprocessed raw dbt
SQL are also not apply-ready for the same reason.

`--diff` prints unified diffs for proven rewrites with generated SQL. It is
read-only and does not modify project files.

`--write-patches DIR` writes patch files for proven rewrites. It also does not
modify project files. Patch file paths preserve the model path and append the
rewrite rule name.

`--apply-patches` applies proven rewrites directly to model SQL files. It is
explicitly opt-in. Snowprove refuses to apply a rewrite when the scan came from
compiled SQL, when raw dbt SQL was statically preprocessed, or when the current
source file no longer exactly matches the verified original SQL.

`--fail-on findings` exits nonzero only when at least one proven rewrite finding
exists. Unsupported SQL, unknown equivalence, missing constraints, and uncompiled
dbt/Jinja are not treated as failures under this policy.

Snowprove does not currently compile dbt projects. A model containing unsupported
dbt/Jinja syntax is reported as `UNSUPPORTED` when `--all` is used.

Use `--compiled-dir` to scan already-compiled dbt SQL. Schema constraints are
still loaded from the source dbt project's `models/` YAML files.

Use `--use-compiled` to auto-discover a single compiled SQL directory under
`target/compiled/`. If `dbt_project.yml` declares a project name, Snowprove
prefers that local compiled project over compiled package directories. If the
directory is missing, empty, or still ambiguous, Snowprove returns a discovery
error instead of guessing.

For compiled scans, Snowprove maps each compiled SQL file back to the matching
source path under `models/` when the relative path exists. Text reports show the
source path first and the scanned compiled path as context; diff output uses the
source path in the unified-diff headers.
