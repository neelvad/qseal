#!/usr/bin/env bash
set -euo pipefail

QSEAL_DIR="${QSEAL_DIR:-/qseal}"
SOLVER_COMMAND="${SOLVER_COMMAND:-$QSEAL_DIR/scripts/sqlsolver_command.sh}"
TIMEOUT="${TIMEOUT:-30}"
REPORT_DIR="${REPORT_DIR:-/tmp/qseal-sqlsolver-pair}"
PAIR_ORIGINAL_PATH="${PAIR_ORIGINAL_PATH:?PAIR_ORIGINAL_PATH is required}"
PAIR_REWRITTEN_PATH="${PAIR_REWRITTEN_PATH:?PAIR_REWRITTEN_PATH is required}"
PAIR_SCHEMA_PATH="${PAIR_SCHEMA_PATH:?PAIR_SCHEMA_PATH is required}"
PAIR_SCHEMA_FORMAT="${PAIR_SCHEMA_FORMAT:-auto}"
PAIR_DIALECT="${PAIR_DIALECT:-snowflake}"
report_path="$REPORT_DIR/pair.verification.json"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required to run QuerySeal inside this container." >&2
  exit 2
fi

for path in "$PAIR_ORIGINAL_PATH" "$PAIR_REWRITTEN_PATH" "$PAIR_SCHEMA_PATH"; do
  if [[ ! -f "$path" ]]; then
    echo "Pair input not found: $path" >&2
    exit 2
  fi
done

mkdir -p "$REPORT_DIR"

echo
echo "SQLSolver pair check"
(
  cd "$QSEAL_DIR"
  UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/qseal-uv-cache}" \
    UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-/tmp/qseal-venv}" \
    UV_LINK_MODE="${UV_LINK_MODE:-copy}" \
    uv run qseal check \
    "$PAIR_ORIGINAL_PATH" \
    "$PAIR_REWRITTEN_PATH" \
    --schema "$PAIR_SCHEMA_PATH" \
    --schema-format "$PAIR_SCHEMA_FORMAT" \
    --dialect "$PAIR_DIALECT" \
    --verifier sqlsolver \
    --solver-command "$SOLVER_COMMAND" \
    --timeout "$TIMEOUT" \
    --format json \
    > "$report_path"
)

cat "$report_path"
