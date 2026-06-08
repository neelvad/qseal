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
- `--reward-margin` requires a minimum cumulative improvement before
  greedy/beam/exhaustive prefer a longer path; fixed/random remain forced
- `snowprove corpus summarize REPORT.json` ranks strategies and classifies task
  rewards, path/reward disagreement, partial errors, and trivial cases
- `snowprove corpus aggregate REPORT...` measures reward variance, winner and
  reward-class changes, and per-strategy path stability across compatible runs

Policy workflows:

- `snowprove corpus export-trajectories REPORT.json --output trajectories.jsonl`
  writes labeled trajectory rows from corpus search reports
- `snowprove policy train-baseline trajectories.jsonl --model-file policy.json`
  trains the current feature-mean action ranker
- `snowprove policy evaluate-baseline trajectories.jsonl --model-file
  policy.json` reports aggregate offline accuracy and reward gaps
- `snowprove policy inspect-baseline trajectories.jsonl --model-file
  policy.json` reports per-state predictions, misses, unacceptable rows, action
  scores, reward gaps, and state SQL
- `snowprove policy holdout-evaluate trajectories.jsonl OUT --include-fixture
  standard-medium` trains excluding a held-out split, evaluates offline labels,
  and compares greedy against policy-abstain on held-out corpus tasks

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
8. A versioned DuckDB corpus defines six seeded fixture profiles and 102
   concrete tasks with stable content fingerprints, including table-scale and
   multi-action predicate-pushdown variations.
9. A corpus runner compares all five search strategies and writes versioned
   JSON reports with per-run and aggregate oracle/performance metrics.
10. A corpus summary command ranks strategies and highlights task disagreement,
    errors, and trivial cases.
11. A repeated-run aggregate command measures strategy reward variance and
    identifies unstable task labels and paths.
12. Search and corpus runs support an explicit reward margin so benchmark
    differences below the configured threshold do not favor longer paths.
13. `snowprove corpus repeat` runs isolated measurements and writes an automatic
    stability aggregate without reusing benchmark caches across runs.
14. The first three-run 53-task measurement completed cleanly with 4 winner
    changes, 4 reward-class changes, and 8 path changes; 9 tasks were unstable,
    mostly compact-fixture or multi-action cases.
15. DuckDB benchmarks calibrate repeated executions toward 5 ms timing batches
    by default, record batch metadata and timing confidence, and
    neutralize rewards only when the batching safety cap cannot reach the
    target duration.
16. A three-run batched measurement reduced instability from 4 to 1 winner
    changes, 4 to 1 reward-class changes, 8 to 2 path changes, and 9 to 3
    unstable tasks. Strategy reward standard deviation fell to roughly
    0.001-0.002.
17. `snowprove corpus inspect-aggregate` drills into unstable tasks across
    source runs, including paths, rewards, medians, speedups, batch sizes, and
    timing confidence.
18. A targeted five-run, 20 ms experiment stabilized left-join elimination as
    positive and predicate pushdown as neutral. The remaining multi-action
    instability comes from independently benchmarked transition rewards making
    cumulative reward path-dependent.
19. Absolute SQL-state benchmarking and content-addressed `query_benchmark`
    caching are available through `--reward-model state`. Completed paths to
    the same SQL telescope to equal rewards within a run.
20. Full-corpus experiments showed state rewards are noisier: 5 ms state
    batches produced 21 unstable tasks, while 20 ms produced 5, compared with
    3 under the default 5 ms paired transition model. Transition remains the
    default; state experiments should currently use at least 20 ms batches.
21. State benchmarking now measures related SQL states in interleaved pairs.
    New states are normalized to a cached neighboring state before receiving
    their own content-addressed cache entry. A three-run, 53-task, 20 ms
    experiment reduced state instability from 5 tasks to 2 with zero winner
    changes. A controlled five-run comparison still found transition rewards
    about 2-3x less variable, so transition remains the default.
22. State-reward corpus search now uses endpoint-aware tie scoring. Completed
    endpoints beat active partial paths only when cumulative rewards are within
    `reward_margin`; materially worse endpoints still lose. A three-run,
    53-task experiment reduced path changes from 2 to 0 with zero winner
    changes.
23. Aggregate reports now include uncertainty-adjusted reward classes. Raw
    reward-class flips are preserved, but near-threshold repeated measurements
    are marked `uncertain` with an uncertainty band and reason.
24. The bundled corpus is now version 4 with 75 tasks. The expansion added
    event-table variants for redundant `DISTINCT`, redundant non-null filters,
    and combined `DISTINCT` plus non-null-filter tasks; it also added medium
    predicate-pushdown coverage and supported non-null plus pushdown
    multi-action tasks.
25. A three-run, 20 ms, 75-task transition repeat completed with 5 winner
    changes, 3 reward-class changes, 0 uncertainty-adjusted reward-class
    changes, 3 uncertain tasks, and 6 path changes. The aggregate artifact was
    written to `/tmp/snowprove-corpus-75-transition-20260608/corpus-aggregate.json`.
26. A matching three-run, 20 ms, 75-task state repeat completed with 2 winner
    changes, 3 reward-class changes, 0 uncertainty-adjusted reward-class
    changes, 3 uncertain tasks, and 1 path change. It used roughly twice the
    benchmark requests, so transition remains the default and state remains an
    experimental comparison mode.
27. `snowprove corpus export-trajectories REPORT.json --output
    trajectories.jsonl` exports completed corpus search paths as JSONL rows.
    Rows include current SQL, available action IDs, chosen action, proposed and
    next SQL, rewards, verifier/timing fields, state-level oracle-best labels
    from observed suffix returns, and task-level oracle path labels.
28. `snowprove policy train-baseline trajectories.jsonl --model-file
    policy.json` trains an interpretable feature-mean action ranker from
    state-level oracle labels. `snowprove policy evaluate-baseline
    trajectories.jsonl --model-file policy.json` reports top-1 state accuracy,
    per-oracle-rule accuracy, and known reward gaps.
29. A same-run sanity check on
    `/tmp/snowprove-corpus-75-transition-20260608/run-001/corpus-run.json`
    exported 308 trajectory rows across 97 labeled states. The baseline policy
    evaluated on the same trajectories reached 96/97 top-1 state accuracy
    (0.9897) with a mean known reward gap of 0.000529. This confirms the
    labels and scorer path are usable, but it is not a held-out result.
30. Baseline policy training/evaluation supports split filters:
    `--include-task`, `--exclude-task`, `--include-fixture`,
    `--exclude-fixture`, `--include-tag`, and `--exclude-tag`. Artifacts record
    the applied filter.
31. A first fixture holdout sanity check trained on the 75-task transition
    trajectories excluding `standard-medium` and evaluated only
    `standard-medium`: 18/18 top-1 state accuracy with zero mean known reward
    gap. This is still a small split, but confirms the filter workflow works.
32. `policy_baseline` is available as a corpus search strategy:
    `snowprove corpus run OUT --strategy policy_baseline --policy-model
    policy.json`. It scores current available actions with the trained baseline
    model and executes the highest-scoring action as a forced rollout.
33. A policy-only full-corpus smoke run using
    `/tmp/snowprove-policy-baseline-20260608/policy.json` completed 75/75
    tasks with mean reward 0.114065, 117 verifier requests, 117 benchmark
    requests, 96 new benchmarks, and no low-confidence steps. The report was
    written to `/tmp/snowprove-policy-strategy-20260608/corpus-run.json`.
34. A shared six-strategy comparison run was written to
    `/tmp/snowprove-policy-comparison-20260608/corpus-run.json`. With
    `--reward-margin 0.05` and 20 ms batches, greedy/beam/exhaustive won all
    75 tasks with mean reward 0.111497. `policy_baseline` matched fixed/random
    at mean reward 0.104772 and 68 wins, because the current policy rollout is
    forced and cannot choose to stop when the best action is below the margin.
35. Loading policy-baseline corpus reports now works with only
    `policy_model_path` in the saved artifact; the in-memory policy model is
    still required to execute a new `policy_baseline` run.
36. `policy_baseline_abstain` is available as a corpus search strategy. It
    scores available actions with the trained baseline policy, evaluates only
    the top-scored action, and stops if that candidate does not beat the
    current state under the configured `reward_margin`.
37. A greedy/forced-policy/abstaining-policy comparison was written to
    `/tmp/snowprove-policy-abstain-20260608/corpus-run.json`. With
    `--reward-margin 0.05` and 20 ms batches, `policy_baseline_abstain` tied
    greedy at mean reward 0.134872 and 74 wins while using fewer evaluations
    (105 verifier/benchmark requests versus greedy's 118). Forced
    `policy_baseline` reached mean reward 0.120825 and 68 wins.
38. `snowprove policy holdout-evaluate TRAJECTORIES OUT --include-fixture X`
    automates held-out experiments. It trains a baseline policy excluding the
    held-out filters, evaluates offline labels on the held-out split, then runs
    held-out corpus tasks with `greedy` and `policy_baseline_abstain`, writing
    `policy.json`, `offline-evaluation.json`, `corpus-run/corpus-run.json`, and
    `holdout-evaluation.json`.
39. A standard-medium fixture holdout was written to
    `/tmp/snowprove-policy-holdout-standard-medium-20260608`. Training used 79
    labeled states and held out 18 states across 15 tasks. Offline accuracy was
    18/18 with zero mean known reward gap. Held-out corpus search tied greedy
    reward/wins at 0.096018 and 15 wins, while `policy_baseline_abstain` used
    21 verifier/benchmark requests versus greedy's 24.
40. Three additional holdout experiments completed:
    - `/tmp/snowprove-policy-holdout-duplicate-heavy-20260608`: held out
      `duplicate-heavy-small`, trained on 75 states, held out 22 states across
      17 tasks, offline accuracy 22/22, tied greedy at reward 0.086410 and
      17 wins, using 23 verifier/benchmark requests versus greedy's 26.
    - `/tmp/snowprove-policy-holdout-events-20260608`: held out
      `table:events`, trained on 73 states, held out 24 states across 20 tasks,
      offline accuracy 24/24, tied greedy at reward 0.132048 and 20 wins,
      using 28 verifier/benchmark requests versus greedy's 32.
    - `/tmp/snowprove-policy-holdout-multiaction-20260608`: held out
      `multi-action`, trained on 54 states, held out 43 states across 21 tasks,
      offline accuracy 42/43 with mean known reward gap 0.001192, tied greedy
      at reward 0.180552 and 21 wins, using 47 verifier/benchmark requests
      versus greedy's 60.
41. Offline policy evaluation now records exact accuracy and margin-adjusted
    accuracy. `evaluate-baseline --reward-margin` and `holdout-evaluate
    --label-margin` treat predictions with observed suffix reward within the
    margin of the oracle action as acceptable, which avoids turning near-tie
    action-order labels into hard misses. In holdout runs, `--reward-margin`
    remains the search decision margin and `--label-margin` defaults to it.
42. Rerunning the multi-action holdout with `--reward-margin 0.05` and
    `--label-margin 0.055` at
    `/tmp/snowprove-policy-holdout-multiaction-label-margin-20260608` kept exact
    accuracy at 42/43 but raised adjusted accuracy to 43/43. Held-out corpus
    search still tied greedy at reward 0.166312 and 21 wins while using 47
    verifier/benchmark requests versus greedy's 60.
43. The bundled corpus is now version 5 with 102 tasks. The expansion added
    an events predicate-pushdown variant, events plus standard-medium coverage
    for non-null plus predicate-pushdown tasks, and a new `double-not-null`
    multi-action family over users, orders, and events. Focused corpus,
    trajectory, and policy tests passed after the expansion.
44. A three-run, 20 ms, 102-task transition repeat completed at
    `/tmp/snowprove-corpus-102-transition-20260608/corpus-aggregate.json`.
    It reported 20 winner changes, 20 raw reward-class changes, 0
    uncertainty-adjusted reward-class changes, 20 uncertain tasks, and 27 path
    changes. Beam and exhaustive won all 102 tasks with mean reward 0.095486;
    greedy won 97 tasks with mean reward 0.091349. The uncertainty-adjusted
    result says the expanded corpus is usable, but many added tasks sit close
    to the neutral threshold.
45. Fresh trajectories from
    `/tmp/snowprove-corpus-102-transition-20260608/run-001/corpus-run.json`
    were exported to `/tmp/snowprove-policy-102-20260608/trajectories.jsonl`:
    425 rows, 147 labeled states, and oracle paths for all 102 tasks.
46. Expanded holdout checks completed with `--reward-margin 0.05`,
    `--label-margin 0.055`, and 20 ms batches:
    - `/tmp/snowprove-policy-102-holdout-multiaction-20260608`: held out
      `multi-action`, trained on 59 states, held out 88 states across 43 tasks,
      exact offline accuracy 85/88 (0.9659), adjusted accuracy 86/88 (0.9773),
      and tied greedy at reward 0.083697 and 43 wins while using 69 oracle
      calls versus greedy's 97.
    - `/tmp/snowprove-policy-102-holdout-standard-medium-20260608`: held out
      `standard-medium`, trained on 115 states, held out 32 states across 22
      tasks, exact/adjusted offline accuracy 30/32 (0.9375), and tied greedy
      at reward 0.060731 and 22 wins while using 28 oracle calls versus
      greedy's 34.
    - `/tmp/snowprove-policy-102-holdout-events-20260608`: held out
      `table:events`, trained on 98 states, held out 49 states across 35 tasks,
      exact/adjusted offline accuracy 48/49 (0.9796), and tied greedy at
      reward 0.083988 and 35 wins while using 41 oracle calls versus greedy's
      50.
    The offline misses are concentrated in redundant non-null action ordering;
    so far they do not translate into worse held-out corpus search rewards.
47. `snowprove policy inspect-baseline TRAJECTORIES --model-file policy.json`
    now recomputes per-state policy predictions and emits a structured
    `baseline_policy_inspection` artifact. It supports the same include/exclude
    split filters as training/evaluation, `--reward-margin`, `--mode
    misses|unacceptable|all`, text/JSON output, `--limit`, and `--report-file`.
    Running it on the 102-task multi-action holdout showed three exact misses:
    `distinct-not-null-orders-standard-medium`,
    `double-not-null-events-standard-medium`, and `distinct-and-not-null`.
    All inspected misses had tied action scores, so the next improvement should
    focus on action-context features or additional corpus examples that break
    redundant-not-null ordering ties.
48. Baseline policy training now ignores states with fewer than two available
    actions when estimating feature win rates. Single-action states remain in
    model metadata and evaluation, but they no longer teach that an action is
    perfect when there was no alternative. The feature extractor now includes
    action-set context: available rule sets, competing rules, target kind,
    target index, same-rule action counts, and same-rule positions.
49. Rerunning the 102-task multi-action holdout with these choice-state
    features at
    `/tmp/snowprove-policy-102-holdout-multiaction-choice-context-20260608`
    kept exact offline accuracy at 85/88 and adjusted accuracy at 86/88, but
    restored held-out search parity: policy-abstain tied greedy at reward
    0.090728 and 43 wins while using 73 oracle calls versus greedy's 101.
    Inspecting the misses still showed tied 0.0 scores because a full
    `multi-action` holdout leaves no choice-state examples to learn from.
50. Rerunning the `standard-medium` holdout at
    `/tmp/snowprove-policy-102-holdout-standard-medium-choice-context-20260608`
    kept exact/adjusted offline accuracy at 30/32 and tied greedy at reward
    0.065391 and 22 wins while using 28 oracle calls versus greedy's 34.
    The remaining exact misses are fixture-specific ordering cases rather than
    broad policy-search failures.

Next:

1. Add targeted choice-state corpus examples that do not all share the
   `multi-action` tag, so held-out splits still contain learnable action-order
   evidence.
2. Consider replacing the feature-mean scorer with a small supervised ranker
   that can handle sparse/unseen context better than averaging win rates.
3. Keep using `policy inspect-baseline` after each experiment to distinguish
   harmless near-ties from real search-reward regressions.

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
