# Candidate Evidence in CI

`qseal candidates evidence` is the review gate for untrusted candidate SQL. Use
it when a human, LLM, optimizer experiment, or another tool has already written
candidate `.sql` files and CI needs one answer:

- which candidates are proven safe,
- which safe candidates have benchmark evidence,
- which candidates must not be applied.

This is separate from `qseal dbt scan`. The scanner finds deterministic cleanup
suggestions directly in a dbt project. Candidate evidence evaluates a provided
set of candidate files and benchmarks only the candidates that verify.

## Recommended Command

```bash
qseal candidates evidence original.sql \
  --candidates-dir generated-candidates \
  --schema schema.yml \
  --fail-on unproven \
  --report-file qseal-candidate-evidence.json \
  --format text
```

`--fail-on unproven` exits nonzero when any candidate is not
`PROVEN_EQUIVALENT`. Leave it off for advisory review runs that should record
the rejected candidates without failing CI.

The text output is organized like a review artifact:

- `Safe and worth considering`
- `Safe, but no clear speedup`
- `Safe, but evidence needs review`
- `Rejected or unproven`

The JSON artifact has `artifact_type: candidate_evidence` and includes the same
classification fields for tools:

- `candidate_count`, `proven_count`, and `benchmarked_count`
- `verification_counts`
- `benchmark_outcomes`
- `results[].review_section`
- `results[].required_tests`
- `results[].review_diff`
- `results[].recommendation`

See [artifacts.md](artifacts.md#candidate_evidence) for the full field list.

## Candidate Directory Contract

At minimum, `--candidates-dir` must contain one or more `.sql` files:

```text
generated-candidates/
  001_remove_distinct.sql
  002_filter_rows.sql
```

Optional `metadata.json` gives reviewer context. It never affects
verification.

```json
{
  "schema_version": 1,
  "artifact_type": "candidate_bundle",
  "source": "manual",
  "candidates": [
    {
      "path": "001_remove_distinct.sql",
      "description": "Remove DISTINCT using the dim_users.user_id contract."
    }
  ]
}
```

## GitHub Actions

For projects that generate candidate files in a prior step, run evidence as a
separate job step and upload the artifact:

```yaml
name: QuerySeal candidate evidence

on:
  pull_request:

jobs:
  candidate-evidence:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install QuerySeal
        run: uv tool install "qseal @ git+https://github.com/neelvad/qseal.git"

      # Replace this with your candidate producer.
      - name: Generate candidates
        run: ./scripts/generate_candidates.sh

      - name: Verify and benchmark candidates
        run: |
          qseal candidates evidence transform/models/dim_users.sql \
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

Run without `--fail-on unproven` when you want the workflow to stay advisory.
That mode is useful for nightly candidate-generation experiments where rejected
or unknown candidates should be inspected but not block a pull request.

## Demo Fixture

The bundled fixture is executable:

```bash
uv run qseal candidates evidence examples/product_demo/original.sql \
  --candidates-dir examples/product_demo/candidates \
  --schema examples/product_demo/dbt_project/models/schema.yml \
  --rows 10000 \
  --warmups 0 \
  --repetitions 1
```

It includes one proven candidate and one unproven candidate, so it exercises both
the safe-review and rejected-review sections.
