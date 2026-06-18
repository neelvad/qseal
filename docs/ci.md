# QuerySeal in CI

The public-v0 CI path is the CLI. QuerySeal is not currently presented as a
published GitHub Marketplace Action. Use a normal workflow step to install the
package and run `qseal`.

The deterministic scanner has no external solver dependency. It can run on pull
requests to produce advisory reports, markdown comments, or JSON artifacts.

## Advisory Scan

This workflow records findings without failing the pull request:

```yaml
name: QuerySeal

on:
  pull_request:
    paths:
      - "**/models/**/*.sql"

jobs:
  scan:
    runs-on: ubuntu-latest

    steps:
      - name: Check out repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Install uv
        uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install QuerySeal
        run: uv tool install "qseal @ git+https://github.com/neelvad/qseal.git"

      - name: Scan changed dbt models
        run: |
          qseal dbt scan . \
            --changed-since origin/${{ github.base_ref }} \
            --format markdown \
            --report-file qseal-report.json

      - name: Upload QuerySeal report
        uses: actions/upload-artifact@v4
        with:
          name: qseal-report
          path: qseal-report.json
```

Once QuerySeal is published to PyPI, the install step can become
`uv tool install qseal`. For a repository that vendors QuerySeal or runs from a
checkout, replace the install step with `uv sync --locked` and use
`uv run qseal ...`.

## Finding-Gated Scan

Use `--fail-on findings` when the policy is "do not merge when a proven rewrite
opportunity exists." `UNKNOWN` and `UNSUPPORTED` results do not fail this
policy.

```bash
qseal dbt scan . \
  --changed-since origin/main \
  --format json \
  --report-file qseal-report.json \
  --fail-on findings
```

## Intake Artifact

For private projects or early design-partner conversations, prefer a redacted
intake artifact before sharing raw scan output:

```bash
qseal dbt intake . --use-compiled --report-file qseal-intake.json
```

The intake artifact omits SQL, model names, file paths, diffs, raw unsupported
reasons, and literal accepted values.

## Markdown Comments

`qseal dbt scan --format markdown` emits a GitHub-comment-friendly markdown
report with a stable `<!-- qseal-scan -->` marker. You can post or update that
comment using your own workflow logic, `gh`, or a small script.

## Compiled dbt SQL

For Jinja-heavy projects, compile first and scan compiled SQL:

```bash
dbt compile
qseal dbt scan . --use-compiled --all --report-file qseal-compiled-report.json
```

Compiled scan findings are useful for review, but they are not directly
apply-ready because QuerySeal verified compiled SQL rather than source model
text.

## Tiers

This page covers the deterministic scanner. Prover-backed workflows with QED or
SQLSolver, and candidate-generation workflows with an LLM, should run
out-of-band unless you have explicitly provisioned those toolchains in CI.
