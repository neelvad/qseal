# Product Thesis and Demo Flow

QuerySeal is not a general SQL optimizer. The product wedge is narrower:

> Data teams already maintain dbt tests that encode facts Snowflake cannot
> safely assume. QuerySeal turns those tests into verified-safe rewrite
> suggestions, then attaches evidence about whether the rewrite is worth
> applying.

The durable claim is semantic safety under declared assumptions. Performance is
measured separately and used for ranking or suppression.

The runnable fixture for this page lives at `examples/product_demo/`.

## What the Demo Should Prove

The demo should leave a reviewer with four concrete takeaways:

1. QuerySeal finds rewrites from existing dbt contracts.
2. Every accepted rewrite carries the tests that must keep passing.
3. Untrusted candidates are gated by verification before they can be used.
4. Snowflake performance evidence is target-engine evidence, not a generic
   promise that every rewrite saves money.

Avoid claiming that QuerySeal beats Snowflake's optimizer in general. The
Snowflake evidence so far says the opposite for many generic rewrites:
Snowflake often normalizes them away. The stronger claim is that
premise-enabled rewrites can matter because the warehouse cannot infer dbt
constraints as trusted execution facts.

## Flow 1: CI Scanner

Start with the pure-Python deterministic tier. It is the product default and
requires no external solver or Snowflake credentials.

```bash
uv run qseal dbt scan examples/product_demo/dbt_project --format text
```

This finds one proven rewrite in the bundled product-demo project:

- `remove_redundant_distinct` on `dim_users.sql`, guarded by `unique` and
  `not_null` tests on `dim_users.user_id`

The important product behavior is not just that rewrites are found. The output
also says whether each rewrite is apply-ready and names the ongoing tests that
make the proof valid.

CI shape:

```bash
qseal dbt scan transform/snowflake-dbt \
  --changed-since origin/main \
  --format markdown
```

That is the pull-request comment surface: reviewable diffs plus explicit
guarding tests. Use `--fail-on findings` only when the team wants to turn
proven findings into an enforcement gate.

## Flow 2: Candidate Gate and Evidence

The same safety boundary works for untrusted candidates from an LLM, a human, or
another tool. The candidate producer is outside the trusted path; QuerySeal only
benchmarks candidates that verify.

```bash
uv run qseal candidates evidence \
  examples/product_demo/original.sql \
  --candidates-dir examples/product_demo/candidates \
  --schema examples/product_demo/dbt_project/models/schema.yml \
  --rows 10000 \
  --warmups 0 \
  --repetitions 1 \
  --format text
```

Expected result: two candidates checked. `001_remove_distinct.sql` is proven by
builtin rule replay and benchmarked; `002_filter_rows.sql` is not proven and is
not benchmarked. In a production candidate flow, use `--fail-on unproven` so
unknown or unsupported candidates cannot pass silently.

```bash
qseal candidates evidence original.sql \
  --candidates-dir generated-candidates \
  --schema schema.yml \
  --fail-on unproven \
  --format json
```

The higher LLM/prover workflow expands this same contract:

```bash
qseal llm generate PROJECT --out bundles/
qseal llm verify bundles/ --qed --report-file verification.json
qseal llm benchmark verification.json bundles/ --report-file duckdb-bench.json
qseal llm explain verification.json bundles/ --report-file snowflake-explain.json
```

The generator proposes. Verification gates. Benchmarks and plans rank the
verified survivors.

## Flow 3: Local Performance Evidence

Once a pair is proven, benchmark it as a separate evidence artifact:

```bash
uv run qseal benchmark \
  examples/product_demo/original.sql \
  examples/product_demo/candidates/001_remove_distinct.sql \
  --setup examples/product_demo/setup.sql \
  --warmups 0 \
  --repetitions 1 \
  --format text
```

This is useful for demonstrating the separation between semantic safety and
performance value. Row-count equality in a benchmark is only a diagnostic; it is
not a proof. The proof must come first.

## Flow 4: Snowflake Family Suite

Use the repeatable Snowflake suite when the question is whether a rewrite family
survives Snowflake's optimizer and execution model:

```bash
uv run qseal benchmark-suite snowflake-family snowflake-family-run \
  --scale 1000000 \
  --mode aggregate \
  --runs 1 \
  --warmups 1 \
  --repetitions 3
```

Required environment variables:

- `QSEAL_SNOWFLAKE_ACCOUNT`
- `QSEAL_SNOWFLAKE_USER`
- `QSEAL_SNOWFLAKE_PASSWORD`
- `QSEAL_SNOWFLAKE_WAREHOUSE`
- `QSEAL_SNOWFLAKE_DATABASE`
- `QSEAL_SNOWFLAKE_SCHEMA`

`QSEAL_SNOWFLAKE_ROLE` is optional. The suite writes generated SQL files,
per-case benchmark artifacts, and one aggregate suite JSON report under the
output directory.

The current small aggregate suite covers:

- redundant `DISTINCT`
- redundant `IS NOT NULL`
- unused `LEFT JOIN`
- `JOIN DISTINCT` to `EXISTS`
- predicate pushdown

A 2026-06-17 1M-row aggregate run classified three families as positive
(`DISTINCT`, unused `LEFT JOIN`, `JOIN DISTINCT` to `EXISTS`), one as neutral or
metadata-noisy (`IS NOT NULL`), and one as neutral / optimizer-normalized
(predicate pushdown). The `DISTINCT` and unused-join aggregate wins include a
metadata-answerable caveat, so the honest claim is aggregate-query evidence, not
a blanket full-result-query claim.

## Demo Narrative

The crisp narrative:

1. "Your dbt tests already describe facts Snowflake cannot trust for planning."
2. "QuerySeal uses those facts only as explicit assumptions and proves the
   rewrite is row-equivalent under those assumptions."
3. "The review output tells you which tests must keep passing."
4. "Then we measure whether applying the safe rewrite is worth it on the target
   engine."

The crisp non-claim:

QuerySeal does not prove a rewrite is faster, does not replace Snowflake's
optimizer, and does not trust unenforced warehouse constraints unless the user
declares them as ongoing assumptions.
