# Rewrite-Policy Gym

QuerySeal includes a small, reproducible environment for SQL rewrite-policy
experiments. It is useful for search, ranking, and RL-style policy work because
the action space is finite and every transition is checked before it can advance.

This is a research surface, not a production optimizer.

The implementation lives under `qseal.research.*`. Historical imports such as
`qseal.environment` and `qseal.corpus` remain as thin compatibility wrappers,
but new research code should import from `qseal.research.environment`,
`qseal.research.search`, `qseal.research.corpus`, and
`qseal.research.policy`.

## Environment Model

An episode starts from a SQL query and a trusted constraint catalog. At each
state:

1. QuerySeal enumerates currently available rewrite actions.
2. A policy, search strategy, or baseline selects an action.
3. QuerySeal applies the action to produce candidate SQL.
4. The transition is verified for semantic safety.
5. If configured, the original and next SQL are benchmarked on DuckDB.
6. The environment records the verified next state, reward, and artifacts.

Unproven transitions do not advance the state. This keeps untrusted policies out
of the trusted path.

## What It Is Good For

- Comparing fixed-order, random, greedy, beam, exhaustive, and learned rewrite
  policies.
- Studying action ordering when multiple safe rewrites compose.
- Exporting trajectory data for offline ranking and policy experiments.
- Measuring how often a policy can match search while using fewer verifier and
  benchmark calls.
- Regressing benchmark stability on deterministic DuckDB fixtures.

## What It Is Not

- It is not evidence that a learned policy improves arbitrary production SQL.
- It is not a general SQL optimizer benchmark.
- It is not a replacement for warehouse-specific performance evidence.
- It does not make unsafe rewrites safe; every candidate step still needs proof.

## Quick Run

Run a small task from the bundled corpus:

```bash
uv run qseal corpus run /tmp/qseal-corpus-smoke \
  --task redundant-distinct-users \
  --strategy fixed_order \
  --strategy greedy \
  --warmups 0 \
  --repetitions 1
```

Run several baselines on the bundled corpus:

```bash
uv run qseal corpus run /tmp/qseal-corpus-run \
  --strategy fixed_order \
  --strategy random \
  --strategy greedy \
  --strategy beam \
  --strategy exhaustive \
  --reward-margin 0.05 \
  --minimum-duration-ms 20
```

Export trajectories:

```bash
uv run qseal corpus export-trajectories \
  /tmp/qseal-corpus-run/corpus-run.json \
  --output /tmp/qseal-trajectories.jsonl
```

Train a simple dependency-free linear ranker:

```bash
uv run qseal policy train-ranker \
  /tmp/qseal-trajectories.jsonl \
  --model-file /tmp/qseal-ranker.json \
  --training-margin 0.05
```

Evaluate a held-out split:

```bash
uv run qseal policy holdout-evaluate \
  /tmp/qseal-trajectories.jsonl \
  /tmp/qseal-holdout \
  --policy-kind ranker \
  --include-fixture standard-medium \
  --reward-margin 0.05
```

## Artifacts

Corpus runs write versioned JSON reports with:

- task IDs and fixture provenance
- strategy paths and cumulative rewards
- verifier and benchmark request counts
- cache hit metrics
- timing confidence fields
- per-task failures, if any

Trajectory exports write JSONL rows suitable for offline policy experiments.
Rows include the current SQL, available actions, chosen action, proposed SQL,
next SQL, reward, verification fields, and observed oracle labels.

## Related Docs

- [rewrite-environment.md](rewrite-environment.md): lower-level environment API.
- [search-baselines.md](search-baselines.md): fixed/random/greedy/beam/exhaustive
  strategies.
- [task-corpus.md](task-corpus.md): bundled DuckDB task corpus.
- [duckdb-fixtures.md](duckdb-fixtures.md): deterministic fixture generation.
