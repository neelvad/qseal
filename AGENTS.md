# QuerySeal Handoff

This file summarizes the current project state and near-term plan so future
sessions can resume quickly.

## Project Goal

QuerySeal is a CLI-first prototype for verified-safe SQL rewrites over a small
SQL/dbt subset. Snowflake remains the likely commercial target, while DuckDB is
the local research and benchmarking dialect. The eventual direction is:

1. A user supplies a base SQL query.
2. An untrusted generator, eventually an LLM, proposes an optimized candidate.
3. QuerySeal verifies semantic equivalence for supported cases.
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
uv run qseal suggest query.sql --schema schema.yml
uv run qseal suggest query.sql --schema schema.yml --all --format json
uv run qseal check original.sql rewritten.sql --schema schema.yml
uv run qseal check original.sql rewritten.sql --schema schema.yml --fail-on unproven --format json
uv run qseal check original.sql rewritten.sql --schema schema.yml --verifier sqlsolver --solver-command 'SQLSOLVER_COMMAND'
uv run qseal fixtures create fixture.duckdb --seed 42
uv run qseal benchmark original.sql rewritten.sql --setup setup.sql --report-file benchmark.json
uv run qseal candidates check original.sql candidates/*.sql --schema schema.yml
uv run qseal candidates check original.sql candidates/*.sql --schema schema.yml --format json
uv run qseal dbt scan .
uv run qseal dbt scan . --all
uv run qseal dbt scan . --diff
uv run qseal dbt scan . --report-file qseal-report.json
uv run qseal dbt scan . --write-patches qseal-patches
uv run qseal dbt scan . --apply-patches
uv run qseal dbt scan . --use-compiled
uv run qseal policy compare-holdouts HOLDOUT.json HOLDOUT.json --label default --label candidate
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

- QuerySeal YAML
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
- five hand-written anchors plus generated task families
- task families expand query variants across selected fixture profiles
- each task resolves to an `EnvironmentTask` with corpus provenance
- task and corpus content fingerprints are independent of checkout paths
- fixture materialization generates one DuckDB database per named profile
- loader rejects duplicate IDs, unknown rules/references, and unsafe paths
- `qseal corpus run OUTPUT_DIR` executes selected tasks and strategies
- run artifacts include paths, rewards, explored nodes, task-shared cache
  metrics, elapsed time, failures, and aggregate strategy summaries
- repeated runs reuse fixture databases and content-addressed oracle caches
- strategies share one task-level oracle result for each unique SQL transition,
  while per-strategy metrics retain logical request and cache-hit counts
- `--reward-margin` requires a minimum cumulative improvement before
  greedy/beam/exhaustive prefer a longer path; fixed/random remain forced
- `qseal corpus summarize REPORT.json` ranks strategies and classifies task
  rewards, path/reward disagreement, partial errors, and trivial cases
- `qseal corpus aggregate REPORT...` measures reward variance, winner and
  reward-class changes, and per-strategy path stability across compatible runs

Policy workflows:

- `qseal corpus export-trajectories REPORT.json --output trajectories.jsonl`
  writes labeled trajectory rows from corpus search reports
- `qseal policy train-baseline trajectories.jsonl --model-file policy.json`
  trains the current feature-mean action ranker
- `qseal policy train-ranker trajectories.jsonl --model-file ranker.json`
  trains a dependency-free linear pairwise action ranker over the same sparse
  action/context features. Pass `--training-margin X` to skip pairwise
  preferences with known reward gaps below `X`.
- `qseal policy evaluate-baseline trajectories.jsonl --model-file
  policy.json` reports aggregate offline accuracy and reward gaps for either
  policy model family
- `qseal policy inspect-baseline trajectories.jsonl --model-file
  policy.json` reports per-state predictions, misses, unacceptable rows, action
  scores, reward gaps, and state SQL
- `qseal policy holdout-evaluate trajectories.jsonl OUT --include-fixture
  standard-medium` trains excluding a held-out split, evaluates offline labels,
  and compares greedy against policy-abstain on held-out corpus tasks. Pass
  `--policy-kind ranker` to use the linear ranker instead of the feature-mean
  baseline.

dbt workflows:

- scans `models/**/*.sql`
- statically resolves simple `{{ ref('model') }}` and
  `{{ source('name', 'table') }}` relation references
- reports unsupported Jinja macros unless compiled SQL is used
- supports `--compiled-dir`
- supports `--use-compiled`
- maps compiled SQL back to source model paths when possible
- skips compiled dbt test SQL and package-only SQL that do not map to source
  model files
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

- `qseal benchmark ORIGINAL REWRITTEN`
- optional persistent `--database` and reproducible `--setup` SQL
- fixed threads, warmups, alternating repeated measurements, and full result
  materialization
- per-query timeout via DuckDB interruption
- captures every sample, median, median absolute deviation, range, cardinality,
  `EXPLAIN` plans, speedup, and runtime versions
- benchmark cardinality is diagnostic only and does not replace verification

Seeded DuckDB fixtures:

- `qseal fixtures create DATABASE`
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
  -v ~/workspace/qseal-eval/SQLSolver:/sqlsolver \
  -v ~/workspace/qseal:/qseal \
  -w /sqlsolver \
  ubuntu:22.04 \
  bash
```

Inside the container:

```bash
apt-get update
apt-get install -y openjdk-17-jdk ca-certificates file
./gradlew fatjar
/qseal/scripts/run_sqlsolver_fixture.sh
CASE_NAME=all /qseal/scripts/run_sqlsolver_fixture.sh
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
  `qseal check ... --fail-on unproven`.
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
8. A versioned DuckDB corpus defines six seeded fixture profiles and 120
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
13. `qseal corpus repeat` runs isolated measurements and writes an automatic
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
17. `qseal corpus inspect-aggregate` drills into unstable tasks across
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
    written to `/tmp/qseal-corpus-75-transition-20260608/corpus-aggregate.json`.
26. A matching three-run, 20 ms, 75-task state repeat completed with 2 winner
    changes, 3 reward-class changes, 0 uncertainty-adjusted reward-class
    changes, 3 uncertain tasks, and 1 path change. It used roughly twice the
    benchmark requests, so transition remains the default and state remains an
    experimental comparison mode.
27. `qseal corpus export-trajectories REPORT.json --output
    trajectories.jsonl` exports completed corpus search paths as JSONL rows.
    Rows include current SQL, available action IDs, chosen action, proposed and
    next SQL, rewards, verifier/timing fields, state-level oracle-best labels
    from observed suffix returns, and task-level oracle path labels.
28. `qseal policy train-baseline trajectories.jsonl --model-file
    policy.json` trains an interpretable feature-mean action ranker from
    state-level oracle labels. `qseal policy evaluate-baseline
    trajectories.jsonl --model-file policy.json` reports top-1 state accuracy,
    per-oracle-rule accuracy, and known reward gaps.
29. A same-run sanity check on
    `/tmp/qseal-corpus-75-transition-20260608/run-001/corpus-run.json`
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
    `qseal corpus run OUT --strategy policy_baseline --policy-model
    policy.json`. It scores current available actions with the trained baseline
    model and executes the highest-scoring action as a forced rollout.
33. A policy-only full-corpus smoke run using
    `/tmp/qseal-policy-baseline-20260608/policy.json` completed 75/75
    tasks with mean reward 0.114065, 117 verifier requests, 117 benchmark
    requests, 96 new benchmarks, and no low-confidence steps. The report was
    written to `/tmp/qseal-policy-strategy-20260608/corpus-run.json`.
34. A shared six-strategy comparison run was written to
    `/tmp/qseal-policy-comparison-20260608/corpus-run.json`. With
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
    `/tmp/qseal-policy-abstain-20260608/corpus-run.json`. With
    `--reward-margin 0.05` and 20 ms batches, `policy_baseline_abstain` tied
    greedy at mean reward 0.134872 and 74 wins while using fewer evaluations
    (105 verifier/benchmark requests versus greedy's 118). Forced
    `policy_baseline` reached mean reward 0.120825 and 68 wins.
38. `qseal policy holdout-evaluate TRAJECTORIES OUT --include-fixture X`
    automates held-out experiments. It trains a baseline policy excluding the
    held-out filters, evaluates offline labels on the held-out split, then runs
    held-out corpus tasks with `greedy` and `policy_baseline_abstain`, writing
    `policy.json`, `offline-evaluation.json`, `corpus-run/corpus-run.json`, and
    `holdout-evaluation.json`.
39. A standard-medium fixture holdout was written to
    `/tmp/qseal-policy-holdout-standard-medium-20260608`. Training used 79
    labeled states and held out 18 states across 15 tasks. Offline accuracy was
    18/18 with zero mean known reward gap. Held-out corpus search tied greedy
    reward/wins at 0.096018 and 15 wins, while `policy_baseline_abstain` used
    21 verifier/benchmark requests versus greedy's 24.
40. Three additional holdout experiments completed:
    - `/tmp/qseal-policy-holdout-duplicate-heavy-20260608`: held out
      `duplicate-heavy-small`, trained on 75 states, held out 22 states across
      17 tasks, offline accuracy 22/22, tied greedy at reward 0.086410 and
      17 wins, using 23 verifier/benchmark requests versus greedy's 26.
    - `/tmp/qseal-policy-holdout-events-20260608`: held out
      `table:events`, trained on 73 states, held out 24 states across 20 tasks,
      offline accuracy 24/24, tied greedy at reward 0.132048 and 20 wins,
      using 28 verifier/benchmark requests versus greedy's 32.
    - `/tmp/qseal-policy-holdout-multiaction-20260608`: held out
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
    `/tmp/qseal-policy-holdout-multiaction-label-margin-20260608` kept exact
    accuracy at 42/43 but raised adjusted accuracy to 43/43. Held-out corpus
    search still tied greedy at reward 0.166312 and 21 wins while using 47
    verifier/benchmark requests versus greedy's 60.
43. The bundled corpus is now version 5 with 102 tasks. The expansion added
    an events predicate-pushdown variant, events plus standard-medium coverage
    for non-null plus predicate-pushdown tasks, and a new `double-not-null`
    multi-action family over users, orders, and events. Focused corpus,
    trajectory, and policy tests passed after the expansion.
44. A three-run, 20 ms, 102-task transition repeat completed at
    `/tmp/qseal-corpus-102-transition-20260608/corpus-aggregate.json`.
    It reported 20 winner changes, 20 raw reward-class changes, 0
    uncertainty-adjusted reward-class changes, 20 uncertain tasks, and 27 path
    changes. Beam and exhaustive won all 102 tasks with mean reward 0.095486;
    greedy won 97 tasks with mean reward 0.091349. The uncertainty-adjusted
    result says the expanded corpus is usable, but many added tasks sit close
    to the neutral threshold.
45. Fresh trajectories from
    `/tmp/qseal-corpus-102-transition-20260608/run-001/corpus-run.json`
    were exported to `/tmp/qseal-policy-102-20260608/trajectories.jsonl`:
    425 rows, 147 labeled states, and oracle paths for all 102 tasks.
46. Expanded holdout checks completed with `--reward-margin 0.05`,
    `--label-margin 0.055`, and 20 ms batches:
    - `/tmp/qseal-policy-102-holdout-multiaction-20260608`: held out
      `multi-action`, trained on 59 states, held out 88 states across 43 tasks,
      exact offline accuracy 85/88 (0.9659), adjusted accuracy 86/88 (0.9773),
      and tied greedy at reward 0.083697 and 43 wins while using 69 oracle
      calls versus greedy's 97.
    - `/tmp/qseal-policy-102-holdout-standard-medium-20260608`: held out
      `standard-medium`, trained on 115 states, held out 32 states across 22
      tasks, exact/adjusted offline accuracy 30/32 (0.9375), and tied greedy
      at reward 0.060731 and 22 wins while using 28 oracle calls versus
      greedy's 34.
    - `/tmp/qseal-policy-102-holdout-events-20260608`: held out
      `table:events`, trained on 98 states, held out 49 states across 35 tasks,
      exact/adjusted offline accuracy 48/49 (0.9796), and tied greedy at
      reward 0.083988 and 35 wins while using 41 oracle calls versus greedy's
      50.
    The offline misses are concentrated in redundant non-null action ordering;
    so far they do not translate into worse held-out corpus search rewards.
47. `qseal policy inspect-baseline TRAJECTORIES --model-file policy.json`
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
    `/tmp/qseal-policy-102-holdout-multiaction-choice-context-20260608`
    kept exact offline accuracy at 85/88 and adjusted accuracy at 86/88, but
    restored held-out search parity: policy-abstain tied greedy at reward
    0.090728 and 43 wins while using 73 oracle calls versus greedy's 101.
    Inspecting the misses still showed tied 0.0 scores because a full
    `multi-action` holdout leaves no choice-state examples to learn from.
50. Rerunning the `standard-medium` holdout at
    `/tmp/qseal-policy-102-holdout-standard-medium-choice-context-20260608`
    kept exact/adjusted offline accuracy at 30/32 and tied greedy at reward
    0.065391 and 22 wins while using 28 oracle calls versus greedy's 34.
    The remaining exact misses are fixture-specific ordering cases rather than
    broad policy-search failures.
51. The bundled corpus is now version 6 with 120 tasks. The expansion added 18
    targeted choice-state calibration tasks without the `multi-action` tag:
    `choice-distinct-not-null` and `choice-double-not-null` families over
    users, orders, and events on standard-small, low-skew-small, and
    standard-medium fixtures. These tasks are meant to give held-out
    `multi-action` experiments some related choice-state training evidence.
52. A one-run, 20 ms, 120-task transition run completed at
    `/tmp/qseal-corpus-120-transition-20260608/corpus-run.json`. All
    strategies completed all tasks. Mean rewards were fixed/random 0.113390,
    greedy 0.116516, and beam/exhaustive 0.121580. Fresh trajectories were
    exported to `/tmp/qseal-policy-120-20260608/trajectories.jsonl`: 539
    rows, 185 labeled states, and oracle paths for all 120 tasks.
53. Rerunning the multi-action holdout with the v6 trajectories at
    `/tmp/qseal-policy-120-holdout-multiaction-20260608` increased the
    training split from 59 to 95 states and held out 90 states across 43 tasks.
    Policy-abstain still tied greedy search at reward 0.092186 and 43 wins
    while using 75 oracle calls versus greedy's 103, but offline exact and
    adjusted accuracy dropped to 84/90 (0.9333). Inspection showed six
    unacceptable misses, mostly cases where the feature-mean scorer strongly
    prefers `remove_redundant_distinct` or predicate 0 while the trajectory
    oracle prefers removing the redundant non-null filter or predicate 1 first.
    This suggests corpus examples alone are not enough for the current
    averaging scorer; a small supervised ranker is now better justified.
54. A dependency-free linear pairwise action ranker is available via
    `qseal policy train-ranker`. It trains on choice states only and stores
    a `linear_policy_model` artifact with sparse feature weights. Generic
    policy loading/scoring now lets `corpus run`, `corpus repeat`,
    `evaluate-baseline`, `inspect-baseline`, and `holdout-evaluate` consume
    either the feature-mean baseline or the linear ranker.
55. Rerunning the v6 multi-action holdout with `--policy-kind ranker` at
    `/tmp/qseal-policy-120-holdout-multiaction-ranker-pairwise-20260608`
    trained on 95 states, including 18 choice states, and made 360 pairwise
    preference updates. It tied greedy search at reward 0.081031 and 43 wins
    while using 69 oracle calls versus greedy's 97. Offline exact/adjusted
    accuracy stayed at 84/90 (0.9333). Inspecting misses showed the ranker had
    learned strong preferences from the choice-calibration families, but those
    preferences conflict with several held-out multi-action trajectory labels.
56. Rerunning the standard-medium holdout with `--policy-kind ranker` at
    `/tmp/qseal-policy-120-holdout-standard-medium-ranker-pairwise-20260608`
    reached 43/44 offline exact/adjusted accuracy (0.9773), tied greedy search
    at reward 0.085675 and 28 wins, and used 42 oracle calls versus greedy's
    54. This is a better search result than the first ranker attempt, but the
    multi-action split still exposes label/data conflict rather than pure model
    capacity limits.
57. The linear ranker now supports margin-filtered training. `train-ranker`
    and `holdout-evaluate --policy-kind ranker` accept `--training-margin`.
    Preferences with known oracle-vs-alternative reward gaps below the margin
    are skipped; unknown reward gaps are retained. The model artifact records
    `training_margin` and `skipped_preference_count`.
58. Rerunning the v6 multi-action holdout with ranker training margins showed
    that 0.02, 0.05, and 0.10 skipped zero preferences in the current training
    split. Offline exact/adjusted accuracy stayed 84/90. A 0.10 run at
    `/tmp/qseal-policy-120-holdout-multiaction-ranker-margin010-20260608`
    tied greedy search at reward 0.094938 and 43 wins while using 69 oracle
    calls versus greedy's 97. A 0.05 run lost one search win. This means the
    current label conflict is not coming from tiny known training gaps.
59. Rerunning the standard-medium holdout with ranker `--training-margin 0.05`
    at `/tmp/qseal-policy-120-holdout-standard-medium-ranker-margin005-20260608`
    kept 43/44 offline exact/adjusted accuracy and tied greedy search at
    reward 0.085962 and 28 wins while using 44 oracle calls versus greedy's 56.
60. `qseal policy inspect-labels` now compares train and holdout oracle
    preference labels from trajectory JSONL without running benchmarks. It can
    group preference counts by action set, rule pair, table tag, fixture, and
    target context, then reports where holdout labels disagree with the train
    majority.
61. Running:
    `uv run qseal policy inspect-labels /tmp/qseal-policy-120-20260608/trajectories.jsonl --train-exclude-tag multi-action --holdout-include-tag multi-action --reward-margin 0.055 --group-by action_set --group-by table --limit 8`
    found 18 train preferences, 28 holdout preferences, 7 groups, and 5
    disagreement groups. The largest disagreement was double not-null on
    `table:orders`; other disagreements were distinct-vs-not-null choices on
    events, orders, and users. This confirms the current ranker issue is
    train/holdout label conflict in specific action contexts, not only a model
    capacity problem.
62. `policy inspect-labels` now reports `coverage_status`,
    `train_only_group_count`, and `holdout_only_group_count`, so missing train
    coverage is visible separately from true train-vs-holdout disagreement.
    Rerunning the v6 multi-action split with
    `--group-by rule_pair --group-by table --group-by target_pair` showed 0
    disagreement groups but 6 holdout-only groups. These include
    `predicate:1 vs predicate:0` for not-null ordering on orders/users and
    `predicate:0 vs query` for distinct-vs-not-null cases on events/orders/users.
    The next policy improvement should probably add targeted calibration tasks
    for these inverse contexts before adding model complexity.
63. The bundled DuckDB corpus is now v7 with 138 tasks. It adds two targeted
    choice-calibration families:
    `choice-not-null-distinct` and `choice-double-not-null-inverse`. These add
    18 tasks total across standard-small, low-skew-small, and standard-medium
    fixtures, covering the missing inverse contexts from `inspect-labels`.
    A smoke run over representative new order tasks completed through
    `corpus run`, and direct environment inspection confirmed the initial
    action sets include `query:distinct` vs `predicate:0` and `predicate:0` vs
    `predicate:1`.
64. A full v7, one-run, 20 ms transition corpus run completed at
    `/tmp/qseal-corpus-138-transition-20260609/corpus-run.json`. All five
    strategies completed all 138 tasks. Mean rewards were fixed/random
    0.108453, greedy 0.114144, and beam/exhaustive 0.122630. Fresh
    trajectories were exported to
    `/tmp/qseal-policy-138-20260609/trajectories.jsonl`: 640 rows, 223
    labeled states, and oracle paths for all 138 tasks.
65. Rerunning `policy inspect-labels` on v7 reduced the target-pair
    multi-action split from 6 holdout-only groups to 2 holdout-only groups.
    Train preferences increased from 18 to 35. Remaining gaps are primarily
    order-key distinct-vs-not-null contexts where the holdout oracle prefers
    `remove_redundant_not_null_filter::predicate:0` over
    `remove_redundant_distinct::query:distinct`.
66. Rerunning the multi-action holdout with the v7 trajectories and ranker at
    `/tmp/qseal-policy-138-holdout-multiaction-ranker-20260609` improved
    offline exact/adjusted accuracy from the v6 84/90 to 86/89 (0.9663). It
    did not fully improve search: policy-abstain reached reward 0.109150 and
    42 wins versus greedy reward 0.110957 and 43 wins, while using 69 oracle
    calls versus greedy's 99. The three remaining unacceptable misses are
    distinct-not-null users/orders key queries where the ranker still strongly
    prefers removing DISTINCT first. Changing ranker epochs from 1 to 20 did
    not change the offline result.
67. `policy inspect-labels` now reports global train/holdout preference counts
    plus per-group majority preferences and majority ratios. On the v7
    multi-action split, global train preferences were reasonably balanced:
    non-null predicate 0 had 18 preferences, DISTINCT had 16, and predicate 1
    had 1. The problematic local groups are not balanced: orders
    `DISTINCT + IS NOT NULL` has train prefs 6/6 for DISTINCT while holdout is
    split 2 DISTINCT vs 2 non-null; users has train 5 DISTINCT vs 1 non-null
    while holdout is 3 DISTINCT vs 1 non-null. This confirms the remaining
    misses are local group-balance issues, not a simple global action-prior
    issue.
68. A attempted v8 key-column calibration expansion was tested but not kept:
    the candidate tasks did not reliably label the intended non-null action
    under the real corpus runner. The better next move was ranker weighting.
69. `train-ranker` and `holdout-evaluate --policy-kind ranker` now support
    `--unknown-preference-scale`. This scales training preferences whose
    alternative action reward was not observed; the default remains 1.0 for
    backward-compatible behavior. `unknown-preference-scale 0` skips those
    labels and records `skipped_unknown_preference_count`.
70. On the v7 trajectories, fully skipping unknown preferences was too
    aggressive: offline multi-action accuracy dropped to 0.7191. Scaling
    unknown preferences to 0.25 kept offline exact/adjusted accuracy at
    86/89 (0.9663), but restored held-out search parity:
    `/tmp/qseal-policy-138-holdout-multiaction-ranker-unknown025-20260609`
    tied greedy at reward 0.104679 and 43 wins while using 73 oracle calls
    versus greedy's 101.
71. The same `--unknown-preference-scale 0.25` regressed the standard-medium
    holdout at
    `/tmp/qseal-policy-138-holdout-standard-medium-ranker-unknown025-20260609`:
    offline exact/adjusted accuracy fell to 47/56 and 48/56, and policy-abstain
    reached only 25 wins versus greedy's 34. The default scale 1.0 on the same
    v7 split at
    `/tmp/qseal-policy-138-holdout-standard-medium-ranker-default-20260609`
    reached 54/56 exact and 55/56 adjusted accuracy, with 33 wins versus
    greedy's 34. The 0.25 scale is therefore useful for the multi-action split
    but not a safe global recommendation.
72. `qseal policy compare-holdouts` compares holdout artifacts by offline
    exact/adjusted accuracy, greedy/policy reward, win deltas, and oracle
    request deltas. It confirmed the tradeoff above: on the multi-action
    split, unknown scale 0.25 tied greedy with 43 wins and used 56 fewer oracle
    calls; on the standard-medium split, it regressed to 25 wins versus
    greedy's 34 despite using 72 fewer oracle calls.
73. `train-ranker` and `holdout-evaluate --policy-kind ranker` now support
    group-specific unknown preference scaling via
    `--unknown-preference-group-scale GROUP SCALE`, with optional
    `--unknown-preference-group-by`. Group keys reuse the same format emitted
    by `policy inspect-labels`; when group scales are supplied without an
    explicit grouping, the default is `action_set, table`. This enables
    experiments that downweight only selected unknown-reward preference groups
    instead of changing the global unknown preference scale.
74. Targeted group-scaling experiments were run against v7 trajectories for
    the distinct-vs-not-null `orders` and `users` groups:
    `/tmp/qseal-policy-138-holdout-multiaction-ranker-group025-20260609`
    and
    `/tmp/qseal-policy-138-holdout-standard-medium-ranker-group025-20260609`.
    The result was not good enough to keep as a recommendation. Multi-action
    stayed at 86/89 offline accuracy but reached only 42 wins and reward
    0.098211 versus greedy's 43 wins and reward 0.110216. Standard-medium
    regressed to 47/56 exact, 48/56 adjusted, 27 wins, and reward 0.038146.
    `inspect-baseline` showed the standard-medium misses are distinct-vs-null
    choice tasks where the ranker now over-prefers removing `IS NOT NULL`
    before DISTINCT. The multi-action misses remain the previous compact and
    duplicate-heavy cases where DISTINCT is still preferred too strongly.
75. The ranker now extracts SQL column-context features from each state SQL
    during both trajectory training/evaluation and live corpus policy scoring.
    These features include direct projection columns, `IS NOT NULL` predicate
    columns, action-specific target columns, and whether an action column is
    projected. A v7 smoke holdout with global unknown scale 1.0 improved the
    practical tradeoff without scalar tuning:
    `/tmp/qseal-policy-138-holdout-standard-medium-ranker-richfeatures-20260609`
    tied greedy at 34 wins and reward 0.095288 while using 112 oracle calls
    versus greedy's 148, with 54/56 exact and 55/56 adjusted offline accuracy.
    `/tmp/qseal-policy-138-holdout-multiaction-ranker-richfeatures-20260609`
    tied greedy at 43 wins and reward 0.091774 while using 146 oracle calls
    versus greedy's 202, with 86/89 exact/adjusted offline accuracy. This
    looks better than global or group-specific unknown-preference scaling.
76. Reporting now distinguishes the trust basis of safe verification results.
    The compatibility status remains `PROVEN_EQUIVALENT`, but JSON/text
    verification artifacts include `safety_claim` and `verification_method`.
    Builtin checks report `VERIFIED_BY_RULE` /
    `builtin_rule_replay`; SQLSolver EQ results report
    `SOLVER_PROVEN_EQUIVALENT` / `sqlsolver`. Suggestion, dbt scan, and patch
    metadata now include `required_tests` derived from trusted assumptions, for
    example `dbt test: unique on dim_users.user_id`.
77. Fresh real-project scans were run after the reporting changes:
    `/qseal-runs/real-projects/20260609T184252Z-raw-post-claims`,
    `/qseal-runs/real-projects/20260609T184426Z-duckdb-compiled-post-claims`,
    and
    `/qseal-runs/real-projects/20260609T184557Z-kestra-compiled-post-claims`.
    Raw scans across seven cloned dbt projects found 10 model SQL files, 8
    unsupported Jinja/block-syntax results, and 0 proven/apply-ready findings.
    Compiled scans for `dbt-labs/jaffle_shop_duckdb` and `kestra-io/dbt-demo`
    each found 5 proven redundant-not-null rewrites, but all were dbt-generated
    test SQL under `target/compiled/.../models/schema.yml/...`, not source model
    SQL. They are useful evidence that guard metadata works, but not real
    optimization opportunities.
78. `--use-compiled` now filters compiled SQL to files that map back to existing
    source model files under `models/`, excluding compiled dbt tests and
    package-only SQL. Filtered real-project reruns:
    `/qseal-runs/real-projects/20260609T185507Z-duckdb-compiled-filtered`
    and
    `/qseal-runs/real-projects/20260609T185520Z-kestra-compiled-filtered`.
    Each compiled scan now reports 5 models, 1 `UNKNOWN` unused-left-join
    finding in `orders.sql`, and 0 proven findings. The previous dbt-test
    redundant-not-null noise is gone.

Next:

1. Use filtered compiled real-project results to decide the next rule investment.
   Current signal points at richer join/reference analysis rather than more
   policy-ranker work.
2. Keep using `policy compare-holdouts` and `policy inspect-baseline` after
   each experiment to distinguish oracle savings, harmless near-ties, and real
   search-reward regressions.
3. Keep using `policy inspect-labels` to identify which action-set/table groups
   need calibration before adding more corpus variations.

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
- optional `qseal ci dbt .` wrapper if command lines become too long

LLM phase, later:

- add an untrusted candidate-generation command
- run every candidate through `check --fail-on unproven`
- never apply or recommend an LLM rewrite unless QuerySeal proves equivalence

RL research phase:

- keep the first policy structured rather than free-form SQL generation
- treat solver `UNKNOWN`, timeout, and unsupported results as unusable rewards
- prevent identity rewrites from becoming the dominant safe policy
- store normalized SQL, schema, fixture, solver version, DuckDB version, plans,
  timings, and reward for every evaluated transition
- scale to small-model SFT/GRPO only after search baselines are established

## LLM Candidate Generator MVP (agreed 2026-06-10)

The prover/refuter architecture is complete enough to gate an untrusted
generator: builtin rule replay, SQLSolver with validated constraint premises,
and the VeriEQL refuter with fragment-level cross-checking. The agreed MVP:

1. **Placement**: offline batch producer writing candidate SQL files plus
   `metadata.json` into the existing `candidates check` bundle contract.
   Not wired into `dbt scan` (keep CI deterministic and free). A wrapper
   pipeline command is a later convenience.
2. **Prompting**: premise-targeted. Hand the model the trusted dbt-test
   constraints explicitly and ask for rewrites that are valid *because* of
   those facts, seeded with the five rule patterns as worked examples.
   (v2: GenRewrite-style natural-language rewrite-rule hint library that
   accumulates across runs.)
3. **Verification cascade**, cheapest first: normalized-identity check
   (also filters trivial reformattings) -> builtin rule replay -> SQLSolver
   -> VeriEQL refutation on non-proven survivors (refuted vs bounded-OK)
   *and* on proven ones (crosscheck gate). Acceptance bar is
   PROVEN_EQUIVALENT only.
4. **Feedback loop**: one-shot for the first run, logging everything.
   (v2: counterexample-guided repair feeding VeriEQL witness databases back
   to the model, 1-2 retries; prerequisite is full witness rendering in the
   driver, which currently captures only the header.)
5. **No performance claims** in the MVP. The headline metric is the proven
   non-identity rewrite rate on real models. Performance evidence waits for
   the Snowflake EXPLAIN track.
6. **Provenance**: extend bundle `metadata.json` with model id, prompt hash,
   temperature, timestamp. Reuse the content-addressed caches and JSONL
   trajectory recorder from the RL track.

Evaluation: run over the parseable GitLab analytics models (~1,100). Four
numbers drive every downstream decision: candidate parse rate (prompt
quality), proven rate (headline), refuted rate (worth of the repair loop),
bounded-OK rate (whether QED integration is needed). Caveat to keep in mind:
a low proven rate is ambiguous between "clean corpus" and "prover gap" —
the bounded-OK pile disambiguates.

QED stays parked until the bounded-OK numbers justify its two-component
toolchain (Calcite parser + Rust prover). VeriEQL is CC BY-NC-SA: external
checkout only, never bundled or shipped.

## Status Update (2026-06-12)

The generator/verifier loop is complete and measured. Current state:

- **Corpus result (GitLab analytics, 341 models, 400 LLM candidates):
  282 proven (70.5%) across 251 models**; 0 refuted, 0 invalid, 0
  prover conflicts. Generation cost ~$4.90 (Batches API).
- **Prover cascade**: builtin -> QED (native, minutes) -> SQLSolver
  (x86 container or Modal). Fragment-diff pair reduction proves
  changed-CTE-only pairs by congruence (never used for refutation).
  QED frontend declares unknown functions as uninterpreted scalars and
  types string-compared columns varchar. Premise discipline everywhere:
  uniqueness is emitted only with trusted non-null (QED UNIQUE and
  SQLSolver PRIMARY KEY are both strict).
- **Refuter**: VeriEQL (external checkout, CC BY-NC — never bundle).
  Cross-checks proven findings; fragment findings check the resolved
  fragment pair.
- **Runners**: local first-class; Modal runs the same scripts sharded
  (full cascade over 400 candidates in 69s, ~$0.30). Image pins QED
  prover/parser and SQLSolver commits.
- **Tier-1 performance evidence** (docs/performance-evidence.md):
  DuckDB benchmarks on schema-conforming synthetic data; 14 faster
  (1.3-2.2x, dedup shapes), 510 neutral, 3 slower (incl. an LLM
  added-DISTINCT candidate). Row-count mismatch between proven sides
  flags premise-violating synthetic data.

Next, in rough priority:

1. Tier-2 performance evidence: Snowflake trial account + EXPLAIN plan
   diffing for proven pairs (roadmap v0.3; blocked on creating the
   trial account).
2. Coverage residue (optional): dialect normalization for QED's
   Calcite frontend (74 parse rejects), schema-attribution
   improvements (43 ambiguity abstentions).
3. Product packaging: surfacing proven+benchmarked findings (ranking
   gate: safe and beneficial are different axes), wider corpora.
4. Parked: counterexample-guided repair (0 refuted = nothing to
   repair), RL track, full witness rendering in the VeriEQL driver.

## Future Research Notes (2026-06-12)

- **Extend QED toward SQLSolver's coverage.** QED (Rust core, MIT) cannot
  prove the join-shaped rewrites SQLSolver handles (unused LEFT JOIN
  elimination, JOIN+DISTINCT to EXISTS). Rather than porting SQLSolver
  (Apache-2.0, so a port is legal), consider contributing the missing
  reasoning to QED's prover, or rebuilding SQLSolver against arm64 Z3
  bindings to escape the x86 container. Any port/extension validates via
  the existing differential harness (multi-prover cross-checks, execution
  grounding on random premise-satisfying databases) and, ideally,
  certificate emission with an independent checker.
- **SATNet-style soft-equivalence ranking layer (research).** A
  differentiable relaxed-equivalence scorer (e.g. SDP relaxation a la
  SATNet, or smooth agreement over sampled databases) used purely to rank
  candidates before the exact provers run. Differentiable where it helps,
  sound where it counts: the exact cascade remains the gate. Relaxations
  must never replace the verification gate (unsound by construction).

## Backlog (2026-06-12)

- **dbt manifest/catalog ingestion** (`--manifest target/manifest.json`).
  A deployment-readiness feature, not an eval-number mover: real dbt
  projects ship `target/manifest.json` (full compiled column lineage) and
  optionally `catalog.json` (real warehouse column types). Ingesting these
  replaces schema reconstruction from `schema.yml` tests and subsumes all
  three "attribution" sub-problems at once — column ambiguity, missing
  relations, and synthetic-DDL type errors. The current eval mirror is
  source-only (no manifest), which is exactly why we hit these gaps;
  measured ceiling of fixing attribution on GitLab alone is only ~3-5% of
  the proven count, so this waits for a real second corpus / deployment.
- **FLATTEN output schema** in the scope-walker (fixed cols seq/key/path/
  index/value/this) — sound, general, but low yield (most targets die at
  the prover on FLATTEN anyway).

## Future Product Direction (2026-06-13)

- **Formal equivalence as a text-to-SQL trust/eval layer.** The NL2SQL
  field (BIRD benchmark, Gemini-SQL2 at 80% on 2026-06-12) scores
  correctness by execution accuracy - run predicted vs gold SQL on one DB,
  compare result sets. This is unsound (the FLEX paper found BIRD EX agrees
  with human experts only ~62% of the time, ~38% wrong, mostly false
  negatives). QuerySeal's prover/refuter cascade is the sound replacement:
  prove the predicted query equivalent to the gold query, or refute with a
  counterexample database. Use cases: (1) a sounder text-to-SQL eval metric
  for the supported SQL fragment (formal where possible, bounded-refute
  elsewhere, fall back to execution only as a last resort); (2) a runtime
  trust gate on machine-generated SQL from any NL2SQL system. Caveat: our
  provers cover a fragment of SQL; arbitrary BIRD/NL2SQL queries exceed it,
  so this is partial adjudication, strongest as a false-positive catcher.

## Parser Coverage Findings (2026-06-13)

Mapped parse blockers among Jinja-clean, premise-bearing models across both
corpora. GitLab already parses ~90% of them; Mattermost only ~46% (its
premise-bearing tables feed join/aggregate-heavy marts). Done: non-SELECT
(UNION) CTE tolerance in fragment enumeration (commit aeb6778, +16 targets,
the single largest cross-corpus blocker). Remaining levers, in rough ROI
order, all incremental (parser coverage has bounded juice since GitLab is
near-saturated):

- **Ordinal/expression GROUP BY** (`group by 1, 2`) - top Mattermost blocker
  (~7); needs group-key representation beyond ColumnRef. For the LLM path
  only target-selection parsing is needed (provers handle aggregates).
- **Column-to-column / expression WHERE predicates** (~14 GitLab) -
  `_comparison` currently requires column-to-literal.
- **Join-heavy marts** (the real Mattermost gap) - parser join support is
  narrow (INNER/LEFT, col=col ON, mostly single-join). Substantial work;
  the structural reason Mattermost target yield is low.
- Recursive CTEs (~5), broader EXISTS (~4) - low frequency.

Net: the union-CTE fix was the clean high-ROI item; the rest are a long
tail. Bigger breadth unlock is join-parser coverage, which is a project, not
a patch.
