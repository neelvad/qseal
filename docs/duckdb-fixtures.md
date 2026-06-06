# DuckDB Fixtures

Snowprove generates benchmark data with deterministic set-based SQL. It does
not use DuckDB `random()`, Python row loops, timestamps, or machine-specific
inputs.

```bash
snowprove fixtures create fixture.duckdb \
  --seed 42 \
  --users 10000 \
  --orders 100000 \
  --events 50000
```

The database contains:

- `users`: unique user keys, controlled active-status selectivity, nullable
  email values, and skewed segment membership
- `orders`: unique order keys, controlled fact-to-dimension cardinality,
  skewed user references, amounts, and nullable coupon values
- `events`: unique event keys and natural keys with a controlled duplicate
  fraction

The generator fixes DuckDB to one thread and writes a versioned manifest with
the input specification, observed distributions, and content fingerprints.
The same seed and specification should produce the same table fingerprints for
the same generator and DuckDB version.

Use `--force` to replace an existing database and manifest. Generation refuses
to overwrite either output by default.

The fixture is directly reusable by the evaluator:

```bash
snowprove benchmark original.sql rewritten.sql \
  --database fixture.duckdb \
  --report-file benchmark.json
```
