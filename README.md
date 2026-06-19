# QuerySeal

QuerySeal is a CLI tool for verified-safe SQL rewrite suggestions over a
constrained dbt/Snowflake/DuckDB SQL subset.

The public-v0 product surface is the **dbt scanner and candidate verifier**:
find small, premise-backed rewrites that are safe under trusted dbt tests or
QuerySeal YAML constraints, then emit reviewable evidence for CI.

The repository also contains an explicitly experimental rewrite-policy research
harness under `qseal.research.*`. That code is useful for controlled DuckDB
search/ranking experiments, but it is not the primary product surface and is
not production query optimization.

QuerySeal is intentionally not a general SQL optimizer, not a full SQL
equivalence prover, and not a warehouse savings guarantee. A proven rewrite
means: for the supported SQL subset, the rewritten query returns the same rows
as the original under the declared assumptions.

## Why This Exists

Warehouses such as Snowflake cannot generally use dbt tests as optimizer
premises. If dbt says a column is unique, non-null, or related to a parent table,
that is valuable semantic information, but it is not an enforced database
constraint. QuerySeal treats those tests as explicit trusted assumptions and
uses them to prove conservative rewrites such as:

- removing redundant `DISTINCT`
- removing redundant `IS NOT NULL` filters
- removing unused `LEFT JOIN`s
- removing FK-backed unused `INNER JOIN`s
- simplifying `COUNT(DISTINCT col)` when `col` is unique and non-null
- removing accepted-values filters and simplifying accepted-values `CASE`
- collapsing narrow `GROUP BY` queries over trusted unique keys
- pushing predicates through simple projection subqueries

The proof is conditional. If a rewrite depends on a dbt `unique`, `not_null`,
`relationships`, or `accepted_values` test, that test must keep passing.

## Install

From a checkout:

```bash
uv sync
uv run qseal --help
```

From PyPI:

```bash
uvx qseal --help
pipx install qseal
```

The default scanner and DuckDB benchmark tools are pure Python.
Optional external solver integrations require user-supplied toolchains:

- **SQLSolver**: optional independent equivalence prover; Apache 2.0 upstream.
- **QED**: optional independent equivalence prover; MIT/Apache-compatible
  upstream components.
- **VeriEQL**: optional bounded refuter for research/evaluation only. It is
  CC BY-NC-SA 4.0 and is not bundled, vendored, or part of a commercial path.

## Quick Demos

Suggest a rewrite for one query:

```bash
uv run qseal suggest examples/dbt/distinct.sql \
  --schema examples/dbt/schema.yml \
  --all
```

Scan a small dbt-like fixture and produce a privacy-preserving intake report:

```bash
uv run qseal dbt intake tests/fixtures/dbt_projects/yield_pack
```

Scan the product demo project for advisory findings:

```bash
uv run qseal dbt scan examples/product_demo/dbt_project --format text
```

## dbt Scanner

The dbt scanner is an advisory workflow for data projects. It scans dbt model
SQL, reads nearby `schema.yml` / `.yaml` tests, and reports proven-safe rewrite
opportunities. It can emit text, JSON, markdown, diffs, patch files, and
redacted intake artifacts.

Recommended first command for a private project:

```bash
uv run qseal dbt intake . --use-compiled --report-file qseal-intake.json
```

The intake artifact is aggregate-only. It omits SQL, model names, file paths,
diffs, raw unsupported reasons, and literal accepted values. It keeps the useful
fit signals: scanned model count, silent model count, proven finding count, rule
counts, required test categories, redacted unsupported reason categories, and
apply-readiness counts.

For local advisory review:

```bash
uv run qseal dbt scan . --all --report-file qseal-report.json
uv run qseal dbt scan . --use-compiled --all --report-file qseal-compiled-report.json
```

For CI today, use the CLI in your workflow. The repository contains workflow
examples, but the project should not be treated as a published Marketplace
Action yet. See [docs/github-actions.md](docs/github-actions.md) and
[docs/ci.md](docs/ci.md).

## Candidate Verification

If another tool, human, or model generates candidate SQL files, keep generation
outside the trusted path and gate candidates with QuerySeal:

```bash
uv run qseal candidates evidence original.sql \
  --candidates-dir generated-candidates \
  --schema schema.yml \
  --fail-on unproven \
  --report-file qseal-candidate-evidence.json
```

Only `PROVEN_EQUIVALENT` candidates should be considered for review. See
[docs/candidate-evidence-ci.md](docs/candidate-evidence-ci.md).

## Experimental Research Surface

The policy/research side exposes QuerySeal's rewrite rules as a finite action
space. An environment step proposes one rewrite action, verifies semantic
safety, optionally benchmarks the transition on DuckDB, and records the reward.

This code lives under `qseal.research.*` and is for experiments in search,
ranking, RL-style policy learning, and verified action selection. It is not
production query optimization. The corresponding CLI groups are hidden from
root help, but remain available as `qseal corpus ...`, `qseal policy ...`, and
`qseal llm ...`; the direct VeriEQL refuter remains available as
`qseal refute ...`.

Useful commands:

```bash
uv run qseal corpus run /tmp/qseal-run \
  --strategy fixed_order \
  --strategy random \
  --strategy greedy \
  --strategy beam \
  --reward-margin 0.05

uv run qseal corpus export-trajectories \
  /tmp/qseal-run/corpus-run.json \
  --output /tmp/qseal-trajectories.jsonl

uv run qseal policy train-ranker \
  /tmp/qseal-trajectories.jsonl \
  --model-file /tmp/qseal-ranker.json
```

The bundled DuckDB corpus is deliberately small and controlled. That is useful
for reproducibility and policy debugging, but it is not evidence that the same
policy improves arbitrary production SQL. See
[docs/rewrite-policy-gym.md](docs/rewrite-policy-gym.md),
[docs/rewrite-environment.md](docs/rewrite-environment.md),
[docs/search-baselines.md](docs/search-baselines.md), and
[docs/task-corpus.md](docs/task-corpus.md).

## What "Proven" Means

QuerySeal reports how a finding was certified:

- **builtin**: a hand-written rule replayed the same rewrite after parsing and
  normalization. This is the default scanner path.
- **SQLSolver / QED**: an external prover returned an equivalence result.
- **VeriEQL**: a bounded refuter found a counterexample or did not find one up
  to a bound. A counterexample is a sound disproof; bounded-OK is evidence, not
  a proof.

Runtime speed is separate from semantic safety. QuerySeal can benchmark proven
pairs with DuckDB or Snowflake helpers, but performance evidence is diagnostic
and workload-specific.

## Supported Inputs

The SQL subset is intentionally conservative:

- direct table sources and simple subquery sources
- narrow non-recursive CTE pass-through chains
- direct, star, and simple aliased scalar projections
- simple `WHERE` predicates joined by `AND`
- simple `EXISTS`
- `INNER JOIN` / `LEFT JOIN` with column equality predicates
- qualified Snowflake relation names
- selected `GROUP BY`, aggregate, window, and `QUALIFY` shapes where a parser or
  rule explicitly supports them

Trusted constraints can come from QuerySeal YAML or dbt `schema.yml` / `.yaml`.
Supported dbt premise types include:

- `unique`
- `not_null`
- `relationships`
- `accepted_values`
- `dbt_utils.unique_combination_of_columns`

Out of scope includes full SQL equivalence, arbitrary subqueries, join
reordering, recursive CTEs, UDFs, semi-structured `VARIANT` / `FLATTEN`, and any
rewrite that QuerySeal cannot verify. Full detail: [docs/scope.md](docs/scope.md).

## Documentation

Product docs:

- [Scope](docs/scope.md): supported SQL, assumptions, and non-goals.
- [Artifacts](docs/artifacts.md): JSON report contracts.
- [GitHub workflow examples](docs/github-actions.md): CLI-based CI examples.
- [Candidate evidence](docs/candidate-evidence-ci.md): verify generated SQL.
- [Performance evidence](docs/performance-evidence.md): benchmark tiers and
  evidence limits.
- [Product demo](docs/product-demo.md): product-shaped demo narrative.
- [Roadmap](docs/roadmap.md): near-term premise/rewrite direction.
- Solver notes: [SQLSolver](docs/sqlsolver-spike.md),
  [QED](docs/qed-spike.md), [VeriEQL](docs/verieql-spike.md).

Experimental research docs:

- [Rewrite-policy gym](docs/rewrite-policy-gym.md): corpus, search, and policy
  experiments.
- [Rewrite environment](docs/rewrite-environment.md): environment API.
- [Search baselines](docs/search-baselines.md): fixed/random/greedy/beam
  strategies.
- [Task corpus](docs/task-corpus.md): bundled DuckDB corpus.

## Public v0 Status

This is an alpha release. The useful public artifact is a reproducible
verified-rewrite CI workbench, not a mature optimizer. If you try it on a real
dbt project, start with `qseal dbt intake` and share the redacted artifact
before sharing source SQL.
