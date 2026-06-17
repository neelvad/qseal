# QuerySeal in CI

The deterministic rule scanner runs in CI with no external solvers — a pure
`pip install qseal`. On a pull request it scans only the dbt models the PR
changed and comments the proven-safe rewrites it finds.

## GitHub Action

Add `.github/workflows/qseal.yml` to your dbt repo:

```yaml
name: qseal
on:
  pull_request:
    paths:
      - "**/models/**/*.sql"

permissions:
  contents: read
  pull-requests: write   # to post the findings comment

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0   # full history so --changed-since can diff
      - uses: your-org/qseal@v0
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        with:
          project: transform/snowflake-dbt        # path to the dbt project
          base-ref: origin/${{ github.base_ref }}  # the PR's base branch
          fail-on: none                            # or 'findings' to block the PR
          comment: "true"
```

The action posts (and idempotently updates) a single PR comment marked with
`<!-- qseal-scan -->`, grouping proven rewrites by review readiness and listing
the dbt tests that keep each proof valid, apply-readiness, a recommendation, and
a diff. Each rewrite returns the same rows under the listed dbt-test assumptions;
no performance claim is made.

### Inputs

| Input | Default | Meaning |
|---|---|---|
| `project` | `.` | Path to the dbt project (contains `models/`). |
| `base-ref` | `""` | Scan only models changed vs this git ref. Empty scans all models. |
| `fail-on` | `none` | `findings` fails the check when proven rewrites exist. |
| `comment` | `true` | Post/update a PR comment. |
| `dialect` | `snowflake` | `snowflake` or `duckdb`. |

## Without the Action

The Action is a thin wrapper over the CLI. Any CI system can run:

```bash
pip install qseal
qseal dbt scan transform/snowflake-dbt \
  --changed-since origin/main --format markdown
```

`--format json --fail-on findings` gives a machine-readable report and a
nonzero exit when proven rewrites are found.

## Tiers

This page covers the **deterministic** tier (hand-written rules, zero external
dependencies) — the right default for CI. The prover-backed and
LLM-generated tiers (`qseal llm ...`) need the QED/SQLSolver toolchain and
an API key and are run out-of-band, not on every PR. See
[llm-candidates.md](llm-candidates.md).
