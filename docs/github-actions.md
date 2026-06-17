# GitHub Actions

These examples assume QuerySeal is already available in the repository through
`uv sync`. They are intended for dbt projects that want CI-visible rewrite
findings before any LLM-generated rewrite flow exists.

## Advisory Scan

This workflow records findings without failing the pull request.

```yaml
name: QuerySeal

on:
  pull_request:

jobs:
  qseal:
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
          uv run qseal dbt scan . \
            --report-file qseal-report.json \
            --write-patches qseal-patches

      - name: Upload QuerySeal report
        uses: actions/upload-artifact@v4
        with:
          name: qseal-report
          path: |
            qseal-report.json
            qseal-patches/**/*.patch
          if-no-files-found: ignore
```

## Finding-Gated Scan

This workflow fails when QuerySeal finds at least one proven rewrite opportunity.
`UNKNOWN` and `UNSUPPORTED` results do not fail this policy.

```yaml
name: QuerySeal

on:
  pull_request:

jobs:
  qseal:
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
          uv run qseal dbt scan . \
            --report-file qseal-report.json \
            --write-patches qseal-patches \
            --fail-on findings

      - name: Upload QuerySeal report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: qseal-report
          path: |
            qseal-report.json
            qseal-patches/**/*.patch
          if-no-files-found: ignore
```

For Jinja-heavy projects, run `dbt compile` first and scan compiled SQL:

```bash
uv run qseal dbt scan . --use-compiled --report-file qseal-report.json
```

Compiled scan findings are useful for review, but they are not directly
apply-ready because QuerySeal verified compiled SQL rather than the source model
text.

## Candidate Evidence

Use this when another step has produced candidate SQL files and CI needs to
verify them before attaching benchmark evidence. `--fail-on unproven` makes the
job fail when any candidate is not `PROVEN_EQUIVALENT`.

```yaml
name: QuerySeal candidate evidence

on:
  pull_request:

jobs:
  qseal-candidates:
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

      # Replace this with an LLM/manual/rule experiment candidate producer.
      - name: Generate candidates
        run: ./scripts/generate_candidates.sh

      - name: Verify and benchmark candidates
        run: |
          uv run qseal candidates evidence transform/models/dim_users.sql \
            --candidates-dir qseal-candidates/dim_users \
            --schema transform/models/schema.yml \
            --fail-on unproven \
            --report-file qseal-candidate-evidence.json

      - name: Upload candidate evidence
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: qseal-candidate-evidence
          path: qseal-candidate-evidence.json
```

The uploaded `candidate_evidence` artifact records proven candidates, rejected
candidates, required tests, benchmark outcomes, review sections, and diffs. See
[candidate-evidence-ci.md](candidate-evidence-ci.md) for the full workflow and
artifact contract.
