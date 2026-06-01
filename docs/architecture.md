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

- `parser`: converts a constrained Snowflake SQL subset into the internal IR.
- `ir`: stores normalized query, predicate, and join objects.
- `constraints`: loads trusted schema assumptions from YAML.
- `rewrites`: proposes hand-written rewrite candidates.
- `verifier`: proves supported original/rewritten query pairs.
- `report`: renders human-readable CLI output.

## Rewrite Registry

`rewrites/registry.py` owns the default rule order used by `snowprove suggest`.
Rules can be added without changing CLI control flow.
