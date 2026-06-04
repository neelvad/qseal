#!/usr/bin/env bash
set -euo pipefail

CASE_NAME="${CASE_NAME:-redundant_distinct}"
SNOWPROVE_DIR="${SNOWPROVE_DIR:-/snowprove}"
FIXTURE_DIR="$SNOWPROVE_DIR/tests/fixtures/solver_compat"
CASES_MANIFEST="$FIXTURE_DIR/cases.yml"
SOLVER_COMMAND="${SOLVER_COMMAND:-$SNOWPROVE_DIR/scripts/sqlsolver_command.sh}"
TIMEOUT="${TIMEOUT:-30}"
REPORT_DIR="${REPORT_DIR:-}"

case_names() {
  if [[ "$CASE_NAME" != "all" ]]; then
    echo "$CASE_NAME"
    return
  fi

  awk '/^[[:space:]]*- name:/ { print $3 }' "$CASES_MANIFEST"
}

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required to run Snowprove inside this container." >&2
  echo "Install it first, then rerun this script." >&2
  exit 2
fi

for name in $(case_names); do
  case_dir="$FIXTURE_DIR/$name"
  report_path=""
  if [[ ! -d "$case_dir" ]]; then
    echo "Fixture case not found: $case_dir" >&2
    exit 2
  fi

  if [[ -n "$REPORT_DIR" ]]; then
    mkdir -p "$REPORT_DIR/check"
    report_path="$REPORT_DIR/check/$name.verification.json"
  fi

  echo
  echo "Case: $name"
  (
    cd "$SNOWPROVE_DIR"
    if [[ -n "$report_path" ]]; then
      UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/snowprove-uv-cache}" \
        UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-/tmp/snowprove-venv}" \
        UV_LINK_MODE="${UV_LINK_MODE:-copy}" \
        uv run snowprove check \
        "$case_dir/original.sql" \
        "$case_dir/rewritten.sql" \
        --schema "$FIXTURE_DIR/schema.yml" \
        --verifier sqlsolver \
        --solver-command "$SOLVER_COMMAND" \
        --timeout "$TIMEOUT" \
        --format json \
        | tee "$report_path"
    else
      UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/snowprove-uv-cache}" \
        UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-/tmp/snowprove-venv}" \
        UV_LINK_MODE="${UV_LINK_MODE:-copy}" \
        uv run snowprove check \
        "$case_dir/original.sql" \
        "$case_dir/rewritten.sql" \
        --schema "$FIXTURE_DIR/schema.yml" \
        --verifier sqlsolver \
        --solver-command "$SOLVER_COMMAND" \
        --timeout "$TIMEOUT" \
        --format json
    fi
  )
done
