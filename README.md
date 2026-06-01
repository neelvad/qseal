# snowprove

Verified-safe SQL rewrites for a constrained Snowflake SQL subset.

Snowprove is an early CLI-first project. The goal is narrow: prove that small,
hand-written SQL rewrite rules are semantically safe under explicit schema
constraints, then leave performance validation to Snowflake `EXPLAIN` or
benchmarks later.

It does **not** claim that a rewrite is always faster. It claims that a supported
rewrite returns the same rows under the declared assumptions.

## Install

```bash
uv sync
```

## Commands

```bash
uv run snowprove suggest examples/distinct/original.sql --schema examples/distinct/schema.yml
uv run snowprove check examples/distinct/original.sql examples/distinct/rewritten.sql --schema examples/distinct/schema.yml
```

`suggest` proposes the first applicable verified rewrite. `check` verifies a
specific original/rewritten query pair.

## Examples

### Redundant DISTINCT Removal

Input:

```sql
SELECT DISTINCT user_id
FROM users;
```

Schema contract:

```yaml
tables:
  users:
    unique:
      - [user_id]
```

Run:

```bash
uv run snowprove suggest examples/distinct/original.sql --schema examples/distinct/schema.yml
```

Result:

```text
Result: PROVEN_EQUIVALENT
Rewrite: remove_redundant_distinct
```

### Predicate Pushdown

Input:

```sql
SELECT user_id, revenue
FROM (
  SELECT user_id, revenue
  FROM orders
) x
WHERE revenue > 0;
```

Run:

```bash
uv run snowprove suggest examples/predicate_pushdown/original.sql --schema examples/distinct/schema.yml
```

Result:

```text
Result: PROVEN_EQUIVALENT
Rewrite: predicate_pushdown
```

### Unused LEFT JOIN Elimination

Input:

```sql
SELECT f.user_id, f.revenue
FROM fact_orders f
LEFT JOIN dim_users u ON f.user_id = u.user_id;
```

Schema contract:

```yaml
tables:
  dim_users:
    unique:
      - [user_id]
```

Run:

```bash
uv run snowprove suggest examples/join_elimination/original.sql --schema examples/join_elimination/schema.yml
```

Result:

```text
Result: PROVEN_EQUIVALENT
Rewrite: remove_unused_left_join
```

## Current Scope

Currently modeled:

- direct column projections
- simple direct table sources
- one simple subquery source
- simple `WHERE` predicates with `AND`
- `LEFT JOIN ... ON a.col = b.col`
- table aliases
- `DISTINCT` removal when projected columns are known unique
- predicate pushdown through simple projection subqueries
- unused `LEFT JOIN` elimination when the joined key is known unique
- trusted constraints loaded from YAML

Explicitly out of scope for now:

- windows and `QUALIFY`
- `ORDER BY` and `LIMIT`
- aggregation and `GROUP BY`
- `OR`, `IN`, `EXISTS`, and subquery predicates
- join reordering
- `INNER JOIN` rewrites
- UDFs
- semi-structured `VARIANT` / `FLATTEN`
- external verifier backends
- Snowflake connections

See [docs/scope.md](docs/scope.md) for the current proof and product boundaries.
