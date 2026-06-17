# Roadmap

QuerySeal is not trying to become a general SQL optimizer. The useful wedge is
smaller and sharper:

1. dbt tests declare trusted premises.
2. QuerySeal proves a conservative rewrite under those premises.
3. CI shows the required tests, patch/diff, and evidence artifacts.
4. Tier 3 benchmarks measure whether the safe rewrite matters on the target
   warehouse.

The roadmap is therefore organized around **premise vocabulary**, not around an
unbounded list of optimizer rewrites.

## Completed Foundation

- CLI commands for `suggest`, `check`, `dbt scan`, candidate verification, local
  benchmarking, and Snowflake benchmark suites.
- Snowflake and DuckDB dialect propagation through parsing, verification,
  scanning, and artifacts.
- dbt model/source `unique`, `not_null`, `relationships`, and dbt-utils
  `unique_combination_of_columns` ingestion.
- Conservative deterministic rewrite rules for:
  - redundant `DISTINCT`
  - redundant `IS NOT NULL`
  - unused `LEFT JOIN`
  - FK-backed `INNER JOIN` elimination
  - `JOIN DISTINCT` to `EXISTS`
  - predicate pushdown through simple projection subqueries
- FK semantics keep premises explicit: relationships prove parent existence for
  non-null child values; child `not_null` and parent `unique` remain separate
  required premises.
- JSON, text, markdown, diff, patch-file, and optional patch-apply review
  surfaces.
- Product demo fixture connecting deterministic dbt scan output to Snowflake
  Tier 3 evidence.
- Snowflake Tier 3 family suite and dbt-like unused-join demo suite.
- DuckDB rewrite-policy research harness with structured actions, search
  baselines, policy models, corpus runs, and stability reports.
- External verifier adapters/spikes for SQLSolver, QED, and VeriEQL.

## Near-Term Product Roadmap

1. **Composite Join Premises**
   - Extend FK premises and join elimination to composite relationships.
   - Teach the join IR to represent conjunctions such as
     `child.k1 = parent.k1 AND child.k2 = parent.k2`.

2. **Accepted Values / Enum Domains**
   - Ingest dbt `accepted_values` as bounded-domain premises.
   - Start with redundant `IN (...)` predicate elimination.
   - Treat NULL behavior explicitly before using these premises for CASE-branch
     or broader predicate rewrites.

3. **Aggregates Over Unique Keys**
   - Start with `COUNT(DISTINCT col) -> COUNT(col)` when `col` is trusted
     unique and non-null.
   - Defer full `GROUP BY pk` collapse until aggregate expression semantics and
     NULL behavior are covered carefully.

## Warehouse Growth Axis

QuerySeal's positioning should stay close to "CI-verified RELY-style
optimization":

- Databricks, BigQuery, Oracle, and other warehouses expose trusted or
  informational constraints that optimizers may use.
- QuerySeal should treat dbt tests as the continuously rechecked source of those
  premises at PR/CI time.
- Cross-warehouse work should focus on premises that warehouses cannot safely
  infer from raw SQL alone.

## Research Backlog

- Mine semantic-query-optimization literature and systems such as WeTune for
  premise-conditioned rewrite candidates.
- Keep LLM-generated candidates outside the trusted path; prove or reject every
  candidate.
- Use empirical data-diffing only as defense-in-depth, never as proof.
- Continue bounded solver experiments for richer SQL fragments and integrity
  constraints.
