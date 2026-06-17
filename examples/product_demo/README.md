# QuerySeal Product Demo

This fixture is a compact end-to-end demo of the product claim:

1. dbt tests define trusted assumptions.
2. QuerySeal proves which rewrites are safe under those assumptions.
3. Untrusted candidates are benchmarked only after they verify.
4. The final output separates safety from performance evidence.

## 1. Scan A dbt Project

```bash
uv run qseal dbt scan examples/product_demo/dbt_project --format text
```

Expected result: one proven `remove_redundant_distinct` finding on
`models/dim_users.sql`, guarded by `unique` and `not_null` tests on
`dim_users.user_id`. The text report places it in "Safe and apply-ready",
includes a recommendation, and shows the review diff.

## 2. Gate Candidate SQL And Attach Evidence

```bash
uv run qseal candidates evidence examples/product_demo/original.sql \
  --candidates-dir examples/product_demo/candidates \
  --schema examples/product_demo/dbt_project/models/schema.yml \
  --rows 10000 \
  --warmups 0 \
  --repetitions 1 \
  --format text
```

The candidates are intentionally mixed:

- `001_remove_distinct.sql` is proven equivalent and benchmarked.
- `002_filter_rows.sql` is not proven and is not benchmarked.

This is the core product boundary: the candidate producer is untrusted, and
performance evidence is attached only after verification.
The text report groups candidates into review sections such as "Safe and worth
considering" and "Rejected or unproven", and includes the required tests plus a
unified diff for proven candidates.

## 3. Benchmark A Proven Pair Directly

```bash
uv run qseal benchmark \
  examples/product_demo/original.sql \
  examples/product_demo/candidates/001_remove_distinct.sql \
  --setup examples/product_demo/setup.sql \
  --warmups 0 \
  --repetitions 1 \
  --format text
```

This command is useful when a reviewer wants to inspect a single verified pair.
Row-count equality in the benchmark is a diagnostic only; the proof comes from
`qseal check` or `qseal candidates evidence`.

## Honest Claim

This demo does not claim every rewrite saves money. It shows the workflow:
prove safety first, then collect evidence about whether a safe rewrite is worth
applying.
