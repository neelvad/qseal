# Architecture

Snowprove is organized around a small internal query representation rather than
directly rewriting sqlglot AST nodes.

## Flow

```text
SQL text
  -> parser/sqlglot_parser.py
  -> ir/model.py
  -> rewrites/registry.py
  -> verifier/check.py
  -> report/text.py
```

## Main Packages

- `parser`: converts a constrained Snowflake or DuckDB SQL subset into the
  internal IR.
- `ir`: stores normalized query, predicate, and join objects.
- `constraints`: loads trusted schema assumptions from YAML.
- `rewrites`: proposes hand-written rewrite candidates.
- `verifier`: proves supported original/rewritten query pairs.
- `benchmark`: measures verified query pairs reproducibly in DuckDB.
- `report`: renders human-readable CLI output.

## Rewrite Registry

`rewrites/registry.py` owns the default rule order used by `snowprove suggest`.
Rules can be added without changing CLI control flow.

## Dialect Contract

Snowflake is the compatibility default. CLI entry points accept an explicit
`--dialect snowflake|duckdb`, and the selected dialect flows through parsing,
verification requests, dbt scan results, and JSON artifacts. Rewrite rules
operate on the shared constrained IR rather than assuming a dialect directly.
