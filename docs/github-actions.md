# GitHub Actions

These examples assume Snowprove is already available in the repository through
`uv sync`. They are intended for dbt projects that want CI-visible rewrite
findings before any LLM-generated rewrite flow exists.

## Advisory Scan

This workflow records findings without failing the pull request.

```yaml
name: Snowprove

on:
  pull_request:

jobs:
  snowprove:
    runs-on: ubuntu-latest

    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: uv sync --locked

      - name: Scan dbt models
        run: |
          uv run snowprove dbt scan . \
            --report-file snowprove-report.json \
            --write-patches snowprove-patches

      - name: Upload Snowprove report
        uses: actions/upload-artifact@v4
        with:
          name: snowprove-report
          path: |
            snowprove-report.json
            snowprove-patches/**/*.patch
          if-no-files-found: ignore
```

## Finding-Gated Scan

This workflow fails when Snowprove finds at least one proven rewrite opportunity.
`UNKNOWN` and `UNSUPPORTED` results do not fail this policy.

```yaml
name: Snowprove

on:
  pull_request:

jobs:
  snowprove:
    runs-on: ubuntu-latest

    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: uv sync --locked

      - name: Scan dbt models
        run: |
          uv run snowprove dbt scan . \
            --report-file snowprove-report.json \
            --write-patches snowprove-patches \
            --fail-on findings

      - name: Upload Snowprove report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: snowprove-report
          path: |
            snowprove-report.json
            snowprove-patches/**/*.patch
          if-no-files-found: ignore
```

For Jinja-heavy projects, run `dbt compile` first and scan compiled SQL:

```bash
uv run snowprove dbt scan . --use-compiled --report-file snowprove-report.json
```

Compiled scan findings are useful for review, but they are not directly
apply-ready because Snowprove verified compiled SQL rather than the source model
text.
