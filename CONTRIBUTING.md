# Contributing

QuerySeal is early and intentionally conservative. Changes should keep the
modeled SQL subset small, explicit, and easy to audit.

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
uv run ruff format .
```

CI runs tests and Ruff on every push to `main` and on pull requests.

## Adding Rewrite Rules

Prefer small, rule-specific changes:

- add parser or IR support only for syntax the rule needs
- reject unsupported SQL explicitly
- add focused rewrite tests
- add `qseal check` verifier coverage
- add example SQL under `examples/`
- document any new assumptions in `docs/scope.md`

Rules should return `UNKNOWN` when a required assumption is missing and
`UNSUPPORTED` when the SQL shape is outside the modeled subset.

## Constraints

QuerySeal treats YAML constraints as trusted input. Do not infer production
truth from Snowflake metadata unless the source is clearly documented and the
tool reports the assumption.

## Commit Style

Keep commits self-contained. Good examples:

```text
Add dbt schema constraint loader
Support IS NULL predicates
Document Snowflake EXPLAIN plan goals
```
