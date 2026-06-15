# snowprove

**Your dbt tests know things your warehouse optimizer can't use. Snowprove turns
them into verified-safe SQL rewrites.**

A warehouse like Snowflake does not enforce `UNIQUE` or `NOT NULL`, so its
optimizer cannot assume them — it must keep a defensive `SELECT DISTINCT` or an
`IS NOT NULL` filter even when the data is, in fact, unique or non-null. But a
dbt `unique` / `not_null` test *is* that guarantee, written down, version
controlled, and re-checked on every run. Snowprove reads those tests as trusted
premises and uses them to prove rewrites the engine structurally cannot perform
— then emits the guarding tests that must keep passing for the rewrite to stay
valid.

It does **not** claim a rewrite is faster. It claims a supported rewrite returns
**the same rows under the declared assumptions** — and separately measures
whether it helps (see [performance evidence](docs/performance-evidence.md)).

## How it works in CI

On a pull request that touches dbt models, Snowprove scans only the changed
models and comments the proven-safe rewrites it finds:

```yaml
# .github/workflows/snowprove.yml
on:
  pull_request:
    paths: ["**/models/**/*.sql"]
permissions:
  contents: read
  pull-requests: write
jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: your-org/snowprove@v0
        env: { GITHUB_TOKEN: "${{ secrets.GITHUB_TOKEN }}" }
        with:
          project: transform/snowflake-dbt
          base-ref: origin/${{ github.base_ref }}
```

The comment lists each rewrite, the dbt tests that keep it valid, whether it is
apply-ready, and a diff. See [docs/ci.md](docs/ci.md). The same thing runs
locally:

```bash
snowprove dbt scan transform/snowflake-dbt --changed-since origin/main --format markdown
```

## The three tiers

| Tier | Engine | Dependencies | Use |
|---|---|---|---|
| **Deterministic** | Hand-written rules + rule-replay verification | Pure Python (`pip install snowprove`) | The CI scanner. Runs anywhere, no external solvers. |
| **Prover-backed** | + [QED](https://github.com/qed-solver) and [SQLSolver](https://github.com/SJTU-IPADS/SQLSolver) equivalence provers | Rust/Java toolchain | Verifies general rewrites beyond the rule shapes, with an independent proof. |
| **LLM-generated** | + an LLM proposing candidates, gated by the prover cascade | Anthropic API key | Finds rewrites no rule encodes; every candidate is proven or discarded. |

The deterministic tier is the product for a data team's CI. The upper tiers run
out of band. Across two production dbt corpora, the LLM+prover pipeline proved
**284 of 406** generated candidates safe (282/400 on GitLab alone, 71%) and
refuted **zero** — see [docs/llm-candidates.md](docs/llm-candidates.md).

## What "proven" means

Snowprove is a portfolio of sound verifiers; a finding is proven if **any** of
them certifies it, and the source is always reported:

- **builtin** — the rewritten query matches what one of Snowprove's
  hand-written rules would produce after IR normalization. Sound if the rules
  are sound (rule-replay, not an independent proof). Reported as
  `VERIFIED_BY_RULE`.
- **SQLSolver / QED** — independent formal equivalence provers (U-expressions /
  Q-expressions over SMT). Reported as `SOLVER_PROVEN_EQUIVALENT`.
- **VeriEQL** — a bounded *refuter*: it produces a counterexample database when
  two queries differ. A counterexample soundly disproves equivalence; finding
  none up to the bound is evidence, never a proof. (CC BY-NC-SA — never
  bundled; see [docs/verieql-spike.md](docs/verieql-spike.md).)

Every constraint-dependent rewrite is conditional on a *time-varying* data
contract: if Snowprove removes a `DISTINCT` because a column is unique, the dbt
`unique` test must keep running or data drift can invalidate the rewrite. Scan
output therefore names the **required ongoing tests** for each finding.

## Install

```bash
uv sync   # development
```

The deterministic tier is a pure-Python package; the prover and LLM tiers need
external toolchains and keys (see the docs below).

## Examples

### Redundant DISTINCT removal — the canonical premise-enabled rewrite

```sql
SELECT DISTINCT user_id FROM dim_users;
```

```yaml
# dbt schema.yml — the unique + not_null tests are the trusted premise
models:
  - name: dim_users
    columns:
      - name: user_id
        tests: [unique, not_null]
```

```bash
uv run snowprove suggest examples/dbt/distinct.sql --schema examples/dbt/schema.yml
# Result: PROVEN_EQUIVALENT  (remove_redundant_distinct)
```

The `unique` + `not_null` tests become the premise; removing the `DISTINCT` is
proven safe *because* of them. (Unique alone is not enough — a NULL-exempt dbt
unique test still allows duplicate NULLs, so Snowprove requires the column be
non-null too.)

### Unused LEFT JOIN elimination

```sql
SELECT f.user_id, f.revenue
FROM fact_orders f
LEFT JOIN dim_users u ON f.user_id = u.user_id;
```

With `dim_users.user_id` unique, the join cannot duplicate or filter rows and
nothing references `u` — so it is removed (`remove_unused_left_join`). Other
built-in rules: redundant `IS NOT NULL` removal, predicate pushdown, and
`JOIN`+`DISTINCT` → `EXISTS`.

## Verifying a specific pair, or refuting one

```bash
# Prove a rewrite with an external solver
snowprove check original.sql rewritten.sql --schema schema.yml --verifier qed

# Search for a counterexample database that disproves a pair
snowprove refute original.sql rewritten.sql --schema schema.yml --verieql-dir /path/to/VeriEQL
```

`check --fail-on unproven` exits nonzero unless the pair is certified — the
contract for gating untrusted (e.g. LLM-generated) candidates.

## The LLM + prover pipeline

```bash
snowprove llm generate PROJECT --out bundles/        # premise-targeted candidates
snowprove llm verify bundles/ --qed --report-file report.json
snowprove llm benchmark report.json bundles/ --report-file bench.json   # Tier-1 DuckDB
snowprove llm explain   report.json bundles/ --report-file plan.json     # Tier-2 Snowflake EXPLAIN
```

The generator proposes; the prover cascade gates; the evidence layers rank
proven rewrites by measured benefit. See
[docs/llm-candidates.md](docs/llm-candidates.md) and
[docs/performance-evidence.md](docs/performance-evidence.md). Verification fans
out across containers via [Modal](docs/llm-candidates.md) (full corpus in ~70s).

## Scope

Snowprove models a deliberately small SQL subset and grows it conservatively.
Currently supported:

- direct / star / aliased scalar (incl. window) projections
- direct tables, simple subquery sources, non-recursive CTE pass-throughs
- proven rewrites inside individual CTE bodies of larger `WITH` queries (even
  when the outer query is itself outside the subset)
- `WHERE` `AND` predicates, simple `EXISTS`, `INNER`/`LEFT JOIN ... ON a=b`,
  opaque `QUALIFY` (treated conservatively)
- `GROUP BY` / aggregate / window projections (parsed; rewritten only where a
  rule or prover applies)
- trusted constraints from Snowprove YAML or dbt `schema.yml`; dbt project scans

Out of scope: `ORDER BY` / `LIMIT`, `OR` / `IN` / general subquery predicates,
join reordering, recursive CTEs, UDFs, semi-structured `VARIANT` / `FLATTEN`,
dbt manifest ingestion (backlog). Full detail in [docs/scope.md](docs/scope.md).

## Docs

- [CI integration](docs/ci.md) — the GitHub Action and `--changed-since`
- [LLM candidates](docs/llm-candidates.md) — generate → verify → measure
- [Performance evidence](docs/performance-evidence.md) — DuckDB + Snowflake EXPLAIN
- [QED](docs/qed-spike.md) · [SQLSolver](docs/sqlsolver-spike.md) ·
  [VeriEQL](docs/verieql-spike.md) — the prover/refuter backends
- [Scope](docs/scope.md) · [Architecture](docs/architecture.md) ·
  [Roadmap](docs/roadmap.md) · [Contributing](CONTRIBUTING.md)

The research surfaces — `snowprove.environment.RewriteEnvironment`, the search
baselines (`snowprove.search`), and the bundled DuckDB task corpus
(`snowprove corpus`) — are documented in
[docs/rewrite-environment.md](docs/rewrite-environment.md),
[docs/search-baselines.md](docs/search-baselines.md), and
[docs/task-corpus.md](docs/task-corpus.md).
