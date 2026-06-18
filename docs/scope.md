# Scope

QuerySeal is intentionally conservative. A query pair is only proven equivalent
when the parser, rewrite rule, and verifier all support the relevant SQL shape.

## Result Statuses

- `PROVEN_EQUIVALENT`: QuerySeal certified the rewrite safe under the displayed
  assumptions. Check `safety_claim` and `verification_method` to distinguish
  builtin rule replay from external solver proof.
- `NOT_EQUIVALENT`: QuerySeal found a rule-specific reason the rewrite can
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
- `candidate_generation`
- `candidate_verifications`
- `candidate_run`
- `dbt_scan`

The `verification` artifact also includes:

- `proven`: boolean shortcut for `status == PROVEN_EQUIVALENT`
- `safety_claim`: for example `VERIFIED_BY_RULE` for builtin rule replay or
  `SOLVER_PROVEN_EQUIVALENT` for an external solver EQ result
- `verification_method`: backend/method that produced the safety claim
- `rule_name`: verifier rule that proved or disproved the pair, when available
- `inputs`: original, rewritten, schema path, and schema format metadata

Use `qseal check ... --fail-on unproven` to exit nonzero unless the query
pair is proven equivalent.

`candidate_verifications` is the batch artifact emitted by
`qseal candidates check`. It contains one verification result per candidate
SQL file and a `proven_count` summary.

For full artifact notes, see `docs/artifacts.md`.

## Verifier Backends

`qseal check` and `qseal candidates check` route verification through a
backend interface. `builtin` uses QuerySeal's internal parser and rule-specific
rewrite replay; approved pairs report `safety_claim: VERIFIED_BY_RULE`.
`sqlsolver` writes one-line SQL pair files plus a schema file, executes a
user-provided SQLSolver command, and maps `EQ` to `PROVEN_EQUIVALENT` with
`safety_claim: SOLVER_PROVEN_EQUIVALENT`, `NEQ` to `NOT_EQUIVALENT`, and
`UNKNOWN`/`TIMEOUT` to `UNKNOWN`. `external` is a generic stub for future solver
integrations.

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

QuerySeal treats this YAML as trusted. It does not currently inspect Snowflake
or production data to validate that the constraint is true.

QuerySeal can also load dbt-style `schema.yml` files with `--schema-format dbt`.
Currently supported dbt model/source tests:

- column `unique` -> trusted single-column unique key
- column `not_null` -> trusted `nullable: false`
- column `relationships` -> trusted single-column foreign key
- column `accepted_values` -> trusted bounded value domain
- relation-level `dbt_utils.unique_combination_of_columns` -> trusted
  composite unique key

These dbt tests are still treated as assumptions. QuerySeal does not run dbt
tests or verify that they passed.
Reports include `required_tests` / "Required ongoing tests" for assumptions
that map directly to dbt-style guard tests.

## Supported Rewrite Rules

### `remove_redundant_distinct`

Removes `DISTINCT` when the projected columns contain a trusted unique key
whose columns are also trusted non-null. Unique keys follow SQL/dbt-test
semantics, so NULL rows are exempt from uniqueness; without the non-null
premise, duplicate NULL rows could make removal unsafe.

### `remove_redundant_count_distinct`

Rewrites `COUNT(DISTINCT col)` to `COUNT(col)` when `col` is trusted unique and
non-null on the direct base table. The first version supports direct table
queries with no joins, no `HAVING`, and no `QUALIFY`; `GROUP BY` is allowed.

### `remove_redundant_accepted_values_filter`

Removes a positive `IN (...)` predicate when the predicate's values exactly
match the trusted `accepted_values` domain and the column is also trusted
non-null. The non-null premise is required because removing `WHERE col IN (...)`
would otherwise allow NULL rows through.

### `predicate_pushdown`

Pushes an outer filter into a simple projection subquery when the filtered
columns are projected unchanged by the subquery.

### `remove_unused_left_join`

Removes an unused `LEFT JOIN` when:

- the joined relation is not projected
- the joined relation is not filtered outside the join condition
- the joined table's join key is trusted unique, including supported composite
  keys

This avoids the common failure mode where a supposedly unused join duplicates
rows because the right side is not actually unique.

### `remove_foreign_key_inner_join`

Removes an unused `INNER JOIN` from a child table to a parent table when:

- the parent relation is not projected, filtered, grouped, or qualified outside
  the join condition
- the child join key has a trusted `relationships` test to the parent key
- the child join key is trusted non-null
- the parent join key is trusted unique

Single-column FK premises can come from dbt `relationships` tests. Composite FK
premises require an explicit QuerySeal YAML `foreign_keys` entry; multiple
independent dbt column relationships are not treated as a composite row-level FK.
The relationship premise proves matching parent existence for non-null child
values; the child `not_null` premise prevents the join from filtering NULL child
rows; and the parent `unique` premise prevents fanout.

### `remove_redundant_not_null_filter`

Removes `IS NOT NULL` predicates when the filtered column is trusted non-null.
This currently applies only to direct table queries.

### `rewrite_join_distinct_to_exists`

Rewrites a narrow `SELECT DISTINCT ... INNER JOIN ...` pattern to `WHERE EXISTS`
when projected columns all come from the left relation and the join is only used
to require at least one matching row. This avoids join row multiplication before
deduplication.

## Non-Goals

QuerySeal does not prove that a query is faster. Runtime depends on Snowflake
optimizer decisions, micro-partitions, clustering, data shape, warehouse size,
caching, and concurrency. Performance validation should be a separate empirical
step.

QuerySeal also does not attempt full Snowflake SQL equivalence. The current
subset is meant to be small enough to audit.

## Supported SQL Shapes

The current parser models direct table sources, one simple subquery source,
direct column projections, star projections, simple aliased scalar projections,
simple `WHERE` predicates joined by `AND`, simple `EXISTS` predicates,
`INNER JOIN`, and `LEFT JOIN`. Join conditions may be one column equality or an
`AND` conjunction of column equalities.

It also resolves narrow non-recursive CTE shapes that commonly appear in dbt
models:

- `SELECT * FROM cte_name` can forward to the referenced CTE body.
- `FROM cte_name` and `JOIN cte_name` can forward through a CTE body only when
  that CTE is a `SELECT *` pass-through over one direct table or another
  pass-through CTE. The resolved base table keeps the CTE name as its alias so
  qualified column references stay bound.

Complex CTEs remain unsupported when their alias is referenced as a source.
That includes aggregating CTEs, filtering CTEs, joining CTEs, recursive CTEs,
and CTEs that project expressions. A reference to such a CTE is never treated
as the trusted base table sharing its name, so dbt model constraints cannot
leak into same-named CTEs.

## Fragment (Subtree) Rewrites

When a whole `WITH` query is outside the supported subset, QuerySeal still
parses each CTE body and the outer `SELECT` as standalone fragments, with only
the CTEs defined before each fragment in scope. Proven rewrites for one
fragment are spliced back into the full query, which preserves whole-query
semantics because the replaced fragment is proven equivalent under the trusted
constraints. Fragment findings report the rewritten full query and name the
CTE they fired in.

## dbt Project Scans

`qseal dbt scan` discovers SQL files under `models/**/*.sql` and dbt schema
files under `models/**/*.yml` and `models/**/*.yaml`.

Compiled Snowflake SQL can use fully qualified relation names such as
`database.schema.model_name`. QuerySeal preserves those qualified names in
generated rewrites while matching dbt constraints by the unqualified model name.

Default scan output reports only proven rewrite findings. `--all` includes
unknown and unsupported results.

Raw dbt scans statically resolve simple `{{ ref('model') }}` and
`{{ source('name', 'table') }}` relation references. QuerySeal does not evaluate
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
explicitly opt-in. QuerySeal refuses to apply a rewrite when the scan came from
compiled SQL, when raw dbt SQL was statically preprocessed, or when the current
source file no longer exactly matches the verified original SQL.

`--fail-on findings` exits nonzero only when at least one proven rewrite finding
exists. Unsupported SQL, unknown equivalence, missing constraints, and uncompiled
dbt/Jinja are not treated as failures under this policy.

QuerySeal does not currently compile dbt projects. A model containing unsupported
dbt/Jinja syntax is reported as `UNSUPPORTED` when `--all` is used.

Use `--compiled-dir` to scan already-compiled dbt SQL. Schema constraints are
still loaded from the source dbt project's `models/` YAML files.

Use `--use-compiled` to auto-discover a single compiled SQL directory under
`target/compiled/`. If `dbt_project.yml` declares a project name, QuerySeal
prefers that local compiled project over compiled package directories. If the
directory is missing, empty, or still ambiguous, QuerySeal returns a discovery
error instead of guessing.

For compiled scans, QuerySeal maps each compiled SQL file back to the matching
source path under `models/` when the relative path exists. Text reports show the
source path first and the scanned compiled path as context; diff output uses the
source path in the unified-diff headers.
