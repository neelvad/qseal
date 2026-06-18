#!/usr/bin/env bash
set -euo pipefail

QSEAL_DIR="${QSEAL_DIR:-/qseal}"
FIXTURE_DIR="$QSEAL_DIR/tests/fixtures/solver_compat"
CASE_NAME="${CASE_NAME:-redundant_distinct}"
RUN_DIR="${RUN_DIR:-/tmp/qseal-sqlsolver-candidates}"
SOLVER_COMMAND="${SOLVER_COMMAND:-$QSEAL_DIR/scripts/sqlsolver_command.sh}"
TIMEOUT="${TIMEOUT:-30}"
REPORT_DIR="${REPORT_DIR:-}"

case_dir="$FIXTURE_DIR/$CASE_NAME"
out_dir="$RUN_DIR/$CASE_NAME"
if [[ -n "$REPORT_DIR" ]]; then
  mkdir -p "$REPORT_DIR/candidates"
  report_path="$REPORT_DIR/candidates/$CASE_NAME.candidate_run.json"
else
  report_path="$RUN_DIR/$CASE_NAME.candidate_run.json"
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required to run QuerySeal inside this container." >&2
  exit 2
fi

if [[ ! -d "$case_dir" ]]; then
  echo "Fixture case not found: $case_dir" >&2
  exit 2
fi

rm -rf "$out_dir"
mkdir -p "$RUN_DIR"

echo
echo "Candidate pipeline smoke: $CASE_NAME"
(
  cd "$QSEAL_DIR"
  UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/qseal-uv-cache}" \
    UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-/tmp/qseal-venv}" \
    UV_LINK_MODE="${UV_LINK_MODE:-copy}" \
    uv run qseal candidates run \
    "$case_dir/original.sql" \
    --schema "$FIXTURE_DIR/schema.yml" \
    --out "$out_dir" \
    --verifier sqlsolver \
    --solver-command "$SOLVER_COMMAND" \
    --timeout "$TIMEOUT" \
    --format json \
    --fail-on unproven \
    > "$report_path"
)

(
  cd "$QSEAL_DIR"
  UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/qseal-uv-cache}" \
    UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-/tmp/qseal-venv}" \
    UV_LINK_MODE="${UV_LINK_MODE:-copy}" \
    uv run python - "$report_path" <<'PY'
import json
import sys
from pathlib import Path

report_path = Path(sys.argv[1])
payload = json.loads(report_path.read_text())

assert payload["artifact_type"] == "candidate_run", payload
assert payload["generation"]["generated_count"] >= 1, payload
assert payload["verification"]["result_count"] >= 1, payload
assert payload["verification"]["proven_count"] >= 1, payload

print(report_path.read_text())
PY
)
