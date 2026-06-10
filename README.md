# snowprove

Verified-safe SQL rewrites for a constrained Snowflake and DuckDB SQL subset.

Snowprove's product wedge is that dbt tests can encode constraints a warehouse
optimizer cannot safely assume. For example, Snowflake may store unenforced
`UNIQUE` metadata and cannot generally remove a defensive `DISTINCT`, but a dbt
`unique` test or an explicit Snowprove schema contract can be treated as a
trusted project assumption. Snowprove uses those assumptions to propose
reviewable SQL simplifications and emits the guarding tests that must keep
running in CI.

Snowprove is an early CLI-first project. The goal is narrow: verify that small,
hand-written SQL rewrite rules are safe under explicit schema constraints, then
leave performance validation to engine plans or benchmarks.

It does **not** claim that a rewrite is always faster. It claims that a supported
rewrite returns the same rows under the declared assumptions.

For the builtin verifier, "safe" means the rewritten query matches the output of
one of Snowprove's supported rewrite rules after IR normalization. That is
rule-replay over hand-written Python rules, not an independent theorem proof.
External solver backends such as SQLSolver are reported separately when they
prove equivalence.

## Install

```bash
uv sync
```

## Commands

```bash
uv run snowprove suggest examples/distinct/original.sql --schema examples/distinct/schema.yml
uv run snowprove suggest query.sql --schema schema.yml --dialect duckdb
uv run snowprove check examples/distinct/original.sql examples/distinct/rewritten.sql --schema examples/distinct/schema.yml
uv run snowprove candidates generate examples/distinct/original.sql --schema examples/distinct/schema.yml --out candidates/
uv run snowprove candidates check examples/distinct/original.sql candidates/*.sql --schema examples/distinct/schema.yml
uv run snowprove candidates run examples/distinct/original.sql --schema examples/distinct/schema.yml --out candidates/
uv run snowprove fixtures create /tmp/snowprove-fixture.duckdb --seed 42
uv run snowprove benchmark examples/benchmark/original.sql examples/benchmark/rewritten.sql --setup examples/benchmark/setup.sql
```

`suggest` proposes the first applicable verified rewrite. `check` verifies a
specific original/rewritten query pair. `candidates generate` writes candidate
SQL files from Snowprove's existing rewrite rules. `candidates check` verifies
multiple generated candidate rewrites against one original query. `candidates
run` does both steps in one command.

Snowflake remains the default dialect for compatibility. Pass
`--dialect duckdb` to `suggest`, `check`, `candidates generate`, `candidates
check`, `candidates run`, or `dbt scan` when processing DuckDB SQL. JSON
artifacts record the selected dialect.

`benchmark` executes a query pair in DuckDB with fixed thread count, warmups,
alternating repeated measurements, full result materialization, per-query
timeouts, and captured `EXPLAIN` plans. It reports observed performance only;
row-count equality is not a proof of semantic equivalence.

```bash
uv run snowprove benchmark \
  examples/benchmark/original.sql \
  examples/benchmark/rewritten.sql \
  --setup examples/benchmark/setup.sql \
  --warmups 2 \
  --repetitions 5 \
  --timeout 30 \
  --threads 1 \
  --format json \
  --report-file benchmark.json
```

`fixtures create` builds a reusable seeded DuckDB database containing `users`,
`orders`, and `events`. Its controls cover row counts, predicate selectivity,
nullability, duplicate natural keys, dimension/fact skew, and segment
cardinality. The adjacent manifest records the requested specification,
observed statistics, DuckDB version, and deterministic table fingerprints.

```bash
uv run snowprove fixtures create benchmark.duckdb \
  --seed 42 \
  --users 10000 \
  --orders 100000 \
  --events 50000 \
  --active-fraction 0.2 \
  --null-fraction 0.1 \
  --duplicate-fraction 0.25 \
  --skew-fraction 0.8

uv run snowprove benchmark original.sql rewritten.sql \
  --database benchmark.duckdb
```

For search or RL experiments, `snowprove.environment.RewriteEnvironment`
provides a framework-neutral `reset(task)` / `step(action_id)` API. It
enumerates structured rewrite actions, verifies every transition before
advancing, and can attach incremental DuckDB log-speedup rewards.
Filesystem-backed wrappers cache solver and benchmark results by canonical
content hash, while an optional JSONL recorder persists auditable training
trajectories.

Fixed-order, seeded random, greedy, beam, and bounded exhaustive search
baselines are available from `snowprove.search`. See
[`docs/search-baselines.md`](docs/search-baselines.md) for their contracts and
usage.

A bundled, versioned DuckDB task corpus provides seeded fixture profiles and
53 reproducible rewrite-search tasks. See
[`docs/task-corpus.md`](docs/task-corpus.md).

```bash
uv run snowprove corpus run snowprove-runs/corpus \
  --task distinct-and-not-null \
  --strategy greedy \
  --strategy beam \
  --reward-margin 0.05

uv run snowprove corpus summarize snowprove-runs/corpus/corpus-run.json

uv run snowprove corpus repeat snowprove-runs/corpus-repeat \
  --runs 3 \
  --reward-margin 0.05 \
  --minimum-duration-ms 5.0 \
  --warmups 2 \
  --repetitions 5

uv run snowprove corpus inspect-aggregate \
  snowprove-runs/corpus-repeat/corpus-aggregate.json

uv run snowprove corpus repeat snowprove-runs/corpus-state \
  --runs 3 \
  --reward-model state \
  --reward-margin 0.05 \
  --minimum-duration-ms 20

uv run snowprove corpus aggregate \
  snowprove-runs/run-1/corpus-run.json \
  snowprove-runs/run-2/corpus-run.json
```

Corpus strategies share task-level verifier and benchmark results, ensuring
identical SQL transitions receive identical rewards within a run. State reward
mode interleaves related DuckDB measurements and anchors each new SQL state to
a cached neighbor before storing it. State-mode search also prefers completed
endpoints over active partial paths when rewards are within the configured
margin.

Useful options:

```bash
uv run snowprove suggest examples/distinct/original.sql --schema examples/distinct/schema.yml --all
uv run snowprove suggest examples/predicate_pushdown/original.sql --schema examples/distinct/schema.yml --rule predicate_pushdown
uv run snowprove check examples/distinct/original.sql examples/distinct/rewritten.sql --schema examples/distinct/schema.yml --format json
uv run snowprove check examples/distinct/original.sql examples/distinct/rewritten.sql --schema examples/distinct/schema.yml --fail-on unproven
uv run snowprove check examples/distinct/original.sql examples/distinct/rewritten.sql --schema examples/distinct/schema.yml --verifier builtin
uv run snowprove check examples/distinct/original.sql examples/distinct/rewritten.sql --schema examples/distinct/schema.yml --verifier external --solver-command qed
uv run snowprove check original.sql rewritten.sql --schema schema.yml --verifier sqlsolver --solver-command '/path/to/sqlsolver-wrapper'
uv run snowprove candidates generate original.sql --schema schema.yml --out candidates/
uv run snowprove candidates generate original.sql --schema schema.yml --out candidates/ --rule remove_redundant_distinct
uv run snowprove candidates check original.sql candidates/*.sql --schema schema.yml --format json
uv run snowprove candidates check original.sql --candidates-dir candidates/ --schema schema.yml --format json
uv run snowprove candidates check original.sql candidates/*.sql --schema schema.yml --fail-on unproven
uv run snowprove candidates run original.sql --schema schema.yml --out candidates/ --format json
uv run snowprove candidates run original.sql --schema schema.yml --out candidates/ --fail-on unproven
uv run snowprove candidates run examples/candidates/original.sql --schema examples/candidates/schema.yml --out /tmp/snowprove-candidates --report-file /tmp/snowprove-candidate-run.json
uv run snowprove candidates check examples/candidates/original.sql --schema examples/candidates/schema.yml --candidates-dir examples/candidates/manual --format json
uv run snowprove suggest examples/dbt/distinct.sql --schema examples/dbt/schema.yml
uv run snowprove dbt scan examples/dbt_project
```

`check --fail-on unproven` exits nonzero unless Snowprove can certify the query
pair as safe. With the default builtin backend, JSON artifacts report
`safety_claim: VERIFIED_BY_RULE` for rule-replay results. With SQLSolver,
successful EQ results report `safety_claim: SOLVER_PROVEN_EQUIVALENT`. This is
the intended contract for future untrusted candidate generators, including
LLM-generated rewrites.

`candidates generate` is the trusted-rule candidate source: it runs Snowprove's
rewrite rules and writes proven rewritten SQL files such as
`001_remove_redundant_distinct.sql`. `candidates check` is the batch verification
form: it loads the original query once, verifies each candidate SQL file
independently, and reports only certified candidates as safe. It
accepts explicit candidate paths or `--candidates-dir candidates/`. `candidates
run` combines generation and verification into one JSON-friendly command, which
is the intended CI shape before LLM candidate generation exists. Use
`--report-file` to write the `candidate_run` JSON artifact while keeping normal
text output on stdout. The default verifier backend is `builtin`, which wraps
Snowprove's internal rule-replay verifier. `sqlsolver` can call an external
SQLSolver command and maps `EQ`, `NEQ`, `UNKNOWN`, and `TIMEOUT` into Snowprove
statuses. `external` remains a generic stub for future solver integrations.

External generators can write candidate SQL files into a directory and
optionally include `metadata.json`. Metadata is only report context; every SQL
file is still verified as untrusted input:

```text
candidates/
  001_manual_distinct_removed.sql
  metadata.json
```

```json
{
  "schema_version": 1,
  "artifact_type": "candidate_bundle",
  "source": "manual",
  "candidates": [
    {
      "path": "001_manual_distinct_removed.sql",
      "source": "manual",
      "description": "Remove DISTINCT from a projection with a trusted unique key."
    }
  ]
}
```

Solver adapter compatibility cases live under
`tests/fixtures/solver_compat/`. They define the small query-pair suite that new
QED/SQLSolver adapters should pass before being exposed as trusted backends.

### SQLSolver Verifier

SQLSolver currently needs an x86_64 Linux environment because its bundled Z3
native libraries are Linux x86-64 binaries. The local smoke-test wrapper starts
the x86 Colima profile and runs both fixed query-pair checks and a
`candidates run --verifier sqlsolver` pipeline check:

```bash
scripts/run_sqlsolver_container_smoke.sh
```

The smoke wrapper writes JSON reports under
`snowprove-runs/sqlsolver-smoke/<timestamp>/`, which is ignored by git.

Inside the container, Snowprove calls SQLSolver through:

```bash
/snowprove/scripts/sqlsolver_command.sh
```

The same backend can verify a single pair:

```bash
uv run snowprove check original.sql rewritten.sql \
  --schema schema.yml \
  --verifier sqlsolver \
  --solver-command scripts/sqlsolver_command.sh \
  --fail-on unproven
```

Or the generated-candidate pipeline:

```bash
uv run snowprove candidates run original.sql \
  --schema schema.yml \
  --out candidates/ \
  --verifier sqlsolver \
  --solver-command scripts/sqlsolver_command.sh \
  --format json \
  --fail-on unproven
```

For the full Colima setup notes, see
[docs/sqlsolver-spike.md](docs/sqlsolver-spike.md).

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

Those assumptions are time-varying data contracts. If Snowprove removes a
defensive `DISTINCT` because `user_id` is unique, the corresponding dbt
`unique` test must keep running; otherwise future data drift can invalidate the
rewrite. JSON and text reports include `required_tests` / "Required ongoing
tests" for constraint-dependent rewrites.

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
run `dbt compile` itself. Compiled SQL files are scanned only when their path can
be mapped back to an existing source model file under `models/`; compiled dbt
test SQL and package-only SQL are ignored.

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
- proven rewrites inside individual CTE bodies of larger `WITH` queries, even
  when the outer query (for example with `GROUP BY` or aggregates) is itself
  outside the supported subset
- simple `WHERE` predicates with `AND`
- `INNER JOIN ... ON a.col = b.col`
- `LEFT JOIN ... ON a.col = b.col`
- simple `WHERE EXISTS (SELECT 1 FROM ... WHERE a.col = b.col)` predicates
- table aliases
- `DISTINCT` removal when projected columns are known unique and non-null
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
