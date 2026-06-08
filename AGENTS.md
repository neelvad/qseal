# Snowprove Handoff

This file summarizes the current project state and near-term plan so future
sessions can resume quickly.

## Project Goal

Snowprove is a CLI-first prototype for verified-safe SQL rewrites over a small
SQL/dbt subset. Snowflake remains the likely commercial target, while DuckDB is
the local research and benchmarking dialect. The eventual direction is:

1. A user supplies a base SQL query.
2. An untrusted generator, eventually an LLM, proposes an optimized candidate.
3. Snowprove verifies semantic equivalence for supported cases.
4. CI reports proven rewrites, patch files, and verification artifacts.

The current product does not prove performance improvement. It proves semantic
equivalence for supported rewrite patterns under trusted schema assumptions.

An additional research direction is verifier-guided rewrite optimization:

1. Generate reproducible DuckDB query and data-distribution tasks.
2. Expose existing rewrite rules as structured actions.
3. Use an equivalence solver as the semantic-safety oracle.
4. Use repeatable DuckDB benchmarks as the performance reward.
5. Compare learned policies with fixed-order, random, greedy, beam-search, and
   exhaustive-search baselines.

## Current Status

The project is a Python/uv CLI package with tests and GitHub CI.

Core commands:

```bash
uv run snowprove suggest query.sql --schema schema.yml
uv run snowprove suggest query.sql --schema schema.yml --all --format json
uv run snowprove check original.sql rewritten.sql --schema schema.yml
uv run snowprove check original.sql rewritten.sql --schema schema.yml --fail-on unproven --format json
uv run snowprove check original.sql rewritten.sql --schema schema.yml --verifier sqlsolver --solver-command 'SQLSOLVER_COMMAND'
uv run snowprove fixtures create fixture.duckdb --seed 42
uv run snowprove benchmark original.sql rewritten.sql --setup setup.sql --report-file benchmark.json
uv run snowprove candidates check original.sql candidates/*.sql --schema schema.yml
uv run snowprove candidates check original.sql candidates/*.sql --schema schema.yml --format json
uv run snowprove dbt scan .
uv run snowprove dbt scan . --all
uv run snowprove dbt scan . --diff
uv run snowprove dbt scan . --report-file snowprove-report.json
uv run snowprove dbt scan . --write-patches snowprove-patches
uv run snowprove dbt scan . --apply-patches
uv run snowprove dbt scan . --use-compiled
```

Snowflake is the compatibility default. SQL-facing commands accept
`--dialect duckdb` to parse, verify, scan, and report DuckDB semantics
explicitly.

Important validation commands:

```bash
UV_CACHE_DIR=.uv-cache uv run pytest
UV_CACHE_DIR=.uv-cache uv run ruff check .
```

Both passed after the latest changes.

## Implemented Capabilities

Supported SQL subset includes:

- direct table sources
- simple subquery sources
- direct column projections
- column projection aliases, for example `user_id AS id`
- star projections, for example `*` and `users.*`
- simple aliased scalar projections such as boolean comparisons, `CASE`, and
  `COALESCE`
- narrow non-recursive CTE pass-through chains, especially dbt-style
  `WITH source AS (...) SELECT * FROM source`
- simple `WHERE` predicates joined by `AND`
- simple `WHERE EXISTS (SELECT 1 FROM ... WHERE a.col = b.col)`
- `INNER JOIN ... ON a.col = b.col`
- `LEFT JOIN ... ON a.col = b.col`
- qualified Snowflake relation names such as `analytics.public.users`

Dialect handling:

- explicit `snowflake` and `duckdb` dialects
- dialect propagation through parsing, nested queries, CTE validation, dbt
  scans, verifier requests, SQLSolver pair runs, and JSON artifacts
- Snowflake remains the default for existing callers

Trusted constraints:

- Snowprove YAML
- dbt `schema.yml` / `.yaml`
- dbt `unique` and `not_null` column tests

Rewrite rules:

- `remove_redundant_distinct`
- `remove_redundant_not_null_filter`
- `remove_unused_left_join`
- `predicate_pushdown`
- `rewrite_join_distinct_to_exists`

Structured rewrite actions:

- every rule exposes `matches()` and `apply_match()`
- `RewriteMatch` records stable rule-local IDs, target kinds/indexes,
  descriptions, and metadata
- registry helpers enumerate and dispatch the finite action space
- redundant non-null filters expose one action per predicate
- legacy `apply()` behavior remains available to current CLI workflows

Rewrite environment:

- framework-neutral `RewriteEnvironment.reset(task)` / `step(action_id)`
- immutable task, observation, action, and transition models
- action IDs use `rule_name::match_id`
- every transition is verified before state advances
- optional injected performance evaluator
- reward is the log speedup from current SQL to next SQL
- unproven transitions terminate without advancing; maximum steps truncate

Caching and trajectories:

- canonical SHA-256 keys over sorted JSON inputs
- atomic filesystem cache under caller-selected roots
- cached verifier keys include SQL, dialect, constraints, backend, namespace,
  and context
- cached benchmark keys include SQL, evaluator settings, namespace, and fixture
  context
- generated fixture table fingerprints should identify benchmark data
- JSONL trajectory records preserve state SQL, proposed SQL, actual next state,
  oracle artifacts, rewards, and termination flags

Search baselines:

- fixed-order and seeded random forced rollouts
- greedy best-improvement search
- beam search with configurable width and SQL-state deduplication
- breadth-first exhaustive search with a strict evaluated-node limit
- immutable result artifacts containing paths, rewards, and search metadata
- environment factories isolate branch state while allowing shared caches

Task corpus:

- bundled `duckdb-v1` corpus installed with the package
- versioned manifest with named fixture profiles and task definitions
- five hand-written anchors plus twenty generated family tasks
- task families expand query variants across selected fixture profiles
- each task resolves to an `EnvironmentTask` with corpus provenance
- task and corpus content fingerprints are independent of checkout paths
- fixture materialization generates one DuckDB database per named profile
- loader rejects duplicate IDs, unknown rules/references, and unsafe paths
- `snowprove corpus run OUTPUT_DIR` executes selected tasks and strategies
- run artifacts include paths, rewards, explored nodes, task-shared cache
  metrics, elapsed time, failures, and aggregate strategy summaries
- repeated runs reuse fixture databases and content-addressed oracle caches
- strategies share one task-level oracle result for each unique SQL transition,
  while per-strategy metrics retain logical request and cache-hit counts
- `snowprove corpus summarize REPORT.json` ranks strategies and classifies task
  rewards, path/reward disagreement, partial errors, and trivial cases

dbt workflows:

- scans `models/**/*.sql`
- statically resolves simple `{{ ref('model') }}` and
  `{{ source('name', 'table') }}` relation references
- reports unsupported Jinja macros unless compiled SQL is used
- supports `--compiled-dir`
- supports `--use-compiled`
- maps compiled SQL back to source model paths when possible
- refuses direct apply when scan came from compiled SQL or normalized raw dbt SQL
- emits text, JSON, diffs, patch files, and report files
- records patch paths inside JSON reports when `--write-patches` is used
- summarizes repeated unsupported/reason messages

Verifier workflows:

- `check` supports `--verifier builtin`, `--verifier external`, and
  `--verifier sqlsolver`
- `candidates check` verifies many generated candidate SQL files against one
  original query
- `candidate_verifications` JSON artifacts include `result_count`,
  `proven_count`, and one verification result per candidate
- SQLSolver backend writes temp one-line SQL pair files plus schema SQL, runs a
  user-provided command, and maps `EQ -> PROVEN_EQUIVALENT`, `NEQ ->
  NOT_EQUIVALENT`, and `UNKNOWN/TIMEOUT -> UNKNOWN`
- Generic `external` backend remains a non-executing stub for future solver
  integrations

CI/reporting:

- versioned JSON artifacts with `schema_version` and `artifact_type`
- `verification` artifacts include `proven`, `rule_name`, and input paths
- `candidate_verifications` artifacts summarize candidate checks
- `dbt_scan` artifacts include summaries, apply readiness, blockers, and patch paths
- `dbt scan --fail-on findings`
- `check --fail-on unproven`
- GitHub Actions examples in `docs/github-actions.md`

DuckDB performance evaluation:

- `snowprove benchmark ORIGINAL REWRITTEN`
- optional persistent `--database` and reproducible `--setup` SQL
- fixed threads, warmups, alternating repeated measurements, and full result
  materialization
- per-query timeout via DuckDB interruption
- captures every sample, median, median absolute deviation, range, cardinality,
  `EXPLAIN` plans, speedup, and runtime versions
- benchmark cardinality is diagnostic only and does not replace verification

Seeded DuckDB fixtures:

- `snowprove fixtures create DATABASE`
- deterministic set-based generation with no `random()` calls
- `users`, `orders`, and `events` tables cover selectivity, nullability,
  join cardinality, skew, duplicates, and table size
- manifests record specifications, observed statistics, engine version, and
  deterministic content fingerprints
- existing outputs require explicit `--force`

Local fixture/eval coverage:

- `tests/fixtures/dbt_projects/jaffle_like/` captures a small dbt-like project
  with ref/source calls, CTEs, projection expressions, unsupported macro use,
  and expected scan counts
- `tests/fixtures/candidates/` captures a small candidate-check workflow
- `tests/fixtures/solver_compat/` captures solver compatibility query pairs:
  `normalized_identity`, `redundant_distinct`, `unsafe_distinct`,
  `unused_left_join`, and `join_distinct_exists`

## Recent Commits

Recent useful commits include:

```text
1dddcdb Add SQLSolver verifier backend
fc2d9aa Document SQLSolver fixture spike
19d384a Add solver compatibility fixtures
460d493 Define external solver adapter contract
30b3164 Add project handoff summary
```

## SQLSolver Spike Notes

SQLSolver builds locally once Java 17 is installed, but its bundled Z3 native
libraries are Linux x86-64 ELF files. Running the jar directly on Apple Silicon
macOS fails at native Z3 loading. The working path is an x86_64 Ubuntu container
via Colima.

Useful setup:

```bash
brew install qemu lima-additional-guestagents
colima start --profile sqlsolver-x86 --arch x86_64 --cpu 2 --memory 4
docker context use colima-sqlsolver-x86
docker run --rm -it \
  -v ~/workspace/snowprove-eval/SQLSolver:/sqlsolver \
  -v ~/workspace/snowprove:/snowprove \
  -w /sqlsolver \
  ubuntu:22.04 \
  bash
```

Inside the container:

```bash
apt-get update
apt-get install -y openjdk-17-jdk ca-certificates file
./gradlew fatjar
/snowprove/scripts/run_sqlsolver_fixture.sh
CASE_NAME=all /snowprove/scripts/run_sqlsolver_fixture.sh
```

Observed successful SQLSolver fixture results:

```text
redundant_distinct: EQ
unsafe_distinct: NEQ
unused_left_join: EQ
join_distinct_exists: EQ
```

The SQLSolver CLI expects one SQL statement per physical line in each input
file. `scripts/run_sqlsolver_fixture.sh` flattens multiline fixtures before
calling SQLSolver.

## Development Style

- Prefer small stacked commits with descriptive messages.
- Go ahead and run git commit with a summary message, but don't push the commit to github.
- Keep rewrites conservative.
- Default to `UNKNOWN` or `UNSUPPORTED` instead of guessing.
- Do not trust Snowflake unenforced constraints unless explicitly supplied as
  trusted assumptions.
- Keep LLM generation out of the trusted path; future LLM candidates must pass
  `snowprove check ... --fail-on unproven`.
- Use `rg` for search.
- Use `apply_patch` for manual edits.
- Do not revert user changes.

## Recommended Next Step

Prepare the regular codebase for a small DuckDB rewrite-policy experiment:

Completed:

1. DuckDB is an explicit parser, CLI, artifact, and verifier dialect.
2. The DuckDB performance evaluator supports warmups, repeated measurements,
   plans, timeouts, fixed threads, full materialization, and version metadata.
3. Seeded DuckDB fixtures cover table size, selectivity, join cardinality,
   uniqueness, nullability, skew, and duplicates.
4. Rewrite rules expose structured matches and applications as a finite action
   space while preserving legacy CLI behavior.
5. A framework-neutral environment provides verified `reset()` / `step()`
   episodes and optional incremental benchmark rewards.
6. Content-addressed verifier/benchmark caches and JSONL trajectory artifacts
   avoid repeated oracle work and preserve experiment data.
7. Fixed-order, seeded random, greedy, beam-search, and bounded exhaustive
   baselines explore the verified rewrite environment.
8. A versioned DuckDB corpus defines four seeded fixture profiles and 25
   concrete tasks with stable content fingerprints.
9. A corpus runner compares all five search strategies and writes versioned
   JSON reports with per-run and aggregate oracle/performance metrics.
10. A corpus summary command ranks strategies and highlights task disagreement,
    errors, and trivial cases.

Next:

1. Run and inspect repeated baseline comparisons to calibrate benchmark noise,
   task difficulty, and useful reward thresholds.
2. Expand the corpus from 25 foundation tasks toward 50-200 systematic task
   variations based on observed gaps.
3. Add a small learned action-ranking policy only after baseline measurements
   are reproducible.

The initial readiness milestone is 50-200 reproducible DuckDB tasks, at least
five structured actions, solver-backed equivalence rewards, repeatable latency
measurement, cached trajectories, and non-RL baselines.

## Likely Future Work

Core SQL hardening:

- more alias forms
- simple casts and scalar functions
- better generated SQL formatting
- less full-file rewrite churn
- more real dbt compiled SQL path shapes

Verifier/reporting:

- structured parse-error codes
- richer counterexamples
- harden SQLSolver schema generation and command invocation
- evaluate QED after SQLSolver path is stable

CI/product:

- PR comments or annotations
- SARIF output
- changed-files-only scanning
- optional `snowprove ci dbt .` wrapper if command lines become too long

LLM phase, later:

- add an untrusted candidate-generation command
- run every candidate through `check --fail-on unproven`
- never apply or recommend an LLM rewrite unless Snowprove proves equivalence

RL research phase:

- keep the first policy structured rather than free-form SQL generation
- treat solver `UNKNOWN`, timeout, and unsupported results as unusable rewards
- prevent identity rewrites from becoming the dominant safe policy
- store normalized SQL, schema, fixture, solver version, DuckDB version, plans,
  timings, and reward for every evaluated transition
- scale to small-model SFT/GRPO only after search baselines are established
