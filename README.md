# snowprove

Verified-safe SQL rewrites for a constrained Snowflake SQL subset.

This is an early CLI-first scaffold. The initial goal is narrow: prove that small,
hand-written rewrite rules are semantically safe under explicit schema constraints.

## Install

```bash
uv sync
```

## Try It

```bash
uv run snowprove suggest examples/distinct/original.sql --schema examples/distinct/schema.yml
```

Expected result:

```text
Result: PROVEN_EQUIVALENT
Rewrite: remove_redundant_distinct
```

## Current Scope

Supported in the first vertical slice:

- a single-table `SELECT`
- explicit projected columns
- `DISTINCT` removal when projected columns are known unique
- trusted constraints loaded from YAML

Explicitly out of scope for now:

- windows and `QUALIFY`
- `ORDER BY` and `LIMIT`
- UDFs
- semi-structured `VARIANT` / `FLATTEN`
- external verifier backends
- Snowflake connections
