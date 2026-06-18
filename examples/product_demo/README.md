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

Expected result: three proven findings in "Safe and apply-ready":

- `remove_redundant_distinct` on `models/dim_users.sql`, guarded by `unique`
  and `not_null` tests on `dim_users.user_id`
- `remove_unused_left_join` on `models/fct_orders.sql`, guarded by `unique` on
  `dim_users.user_id`
- `remove_foreign_key_inner_join` on `models/fct_orders_fk.sql`, guarded by a
  `relationships` test from `stg_orders.user_id` to `dim_users.user_id`,
  `not_null` on `stg_orders.user_id`, and `unique` on `dim_users.user_id`

The join findings are the local deterministic versions of the Snowflake Tier-3
dbt demo cases: order models join `dim_users` but project only order columns,
so trusted dbt tests make the joins removable.

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

## 4. Measure The dbt-Like Join Case On Snowflake

With Snowflake credentials configured:

```bash
uv run qseal benchmark-suite snowflake-dbt-demo snowflake-dbt-demo-run \
  --scale 1000000 \
  --mode materialized \
  --runs 1 \
  --warmups 1 \
  --repetitions 3
```

This produces target-engine evidence for the same join-elimination families
surfaced by the `fct_orders.sql` and `fct_orders_fk.sql` scan findings.

## Honest Claim

This demo does not claim every rewrite saves money. It shows the workflow:
prove safety first, then collect evidence about whether a safe rewrite is worth
applying.
