# JSON Artifacts

Snowprove JSON output is intended for CI and review tooling. Every artifact has:

- `schema_version`: currently `1`
- `artifact_type`: identifies the payload shape

Only `PROVEN_EQUIVALENT` should be treated as safe. `UNKNOWN`, `UNSUPPORTED`,
and `NOT_EQUIVALENT` are not safe rewrite approvals.

## `verification`

Emitted by:

```bash
snowprove check ... --format json
```

Important fields:

- `status`: verifier result
- `proven`: true only for `PROVEN_EQUIVALENT`
- `rule_name`: rule/backend that produced the result
- `inputs`: original, rewritten, and schema paths
- `assumptions`: trusted assumptions used by the proof
- `counterexample`: optional counterexample text

## `candidate_generation`

Emitted by:

```bash
snowprove candidates generate ... --format json
```

Important fields:

- `original_path`
- `output_dir`
- `generated_count`
- `skipped_count`
- `generated`: candidate file paths and producing rules
- `skipped`: rule results without candidate SQL

## `candidate_verifications`

Emitted by:

```bash
snowprove candidates check ... --format json
```

Important fields:

- `result_count`
- `proven_count`
- `results`: one `verification`-like object per candidate
- `candidate_metadata`: optional metadata from `metadata.json` when
  `--candidates-dir` is used

Candidate metadata is report context only. It does not affect verification.

## `candidate_run`

Emitted by:

```bash
snowprove candidates run ... --format json
snowprove candidates run ... --report-file candidate-run.json
```

Important fields:

- `generation`: same summary shape as `candidate_generation`
- `verification`: same summary shape as `candidate_verifications`

This is the preferred artifact for a candidate-producing CI step.

## `dbt_scan`

Emitted by:

```bash
snowprove dbt scan ... --format json
snowprove dbt scan ... --report-file snowprove-report.json
```

Important fields:

- `model_count`
- `proven_finding_count`
- `summary`: counts by status, rule, and reason
- `results`: model-level findings
- `apply_ready`: whether a proven rewrite can be directly applied
- `apply_blocker`: reason direct apply is unavailable
- `patches`: patch paths when `--write-patches` is used
