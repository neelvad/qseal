# Changelog

## 0.1.0 - Unreleased

- Add conservative SQL rewrite suggestions for a constrained Snowflake/dbt subset.
- Add `suggest`, `check`, `candidates generate`, `candidates check`,
  `candidates run`, and `dbt scan` CLI workflows.
- Add versioned JSON artifacts for suggestions, verification, candidates, and dbt scans.
- Add optional SQLSolver verifier backend and local x86_64 Colima smoke workflow.
- Add candidate bundle metadata for external/manual future LLM candidate producers.
