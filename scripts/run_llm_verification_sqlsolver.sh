#!/usr/bin/env bash
# Run the LLM-candidate SQLSolver verification pass inside the x86 container.
#
#   scripts/run_llm_verification_sqlsolver.sh BUNDLES_DIR REPORT_FILE
#
# BUNDLES_DIR and REPORT_FILE must live inside the QuerySeal repo. Constraints
# come from BUNDLES_DIR/constraints.json (written by the generator), so no
# project mount is needed. Merge the result with the macOS builtin+VeriEQL
# report via verify_llm_candidates.py --merge-reports.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QSEAL_DIR="${QSEAL_DIR:-${SNOWPROVE_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}}"
SQLSOLVER_DIR="${SQLSOLVER_DIR:-$HOME/workspace/qseal-eval/SQLSolver}"
COLIMA_PROFILE="${COLIMA_PROFILE:-sqlsolver-x86}"
COLIMA_CPUS="${COLIMA_CPUS:-2}"
COLIMA_MEMORY="${COLIMA_MEMORY:-4}"
STOP_COLIMA="${STOP_COLIMA:-1}"
SMOKE_IMAGE="${SMOKE_IMAGE:-qseal-sqlsolver-smoke:latest}"
SOLVER_TIMEOUT="${SOLVER_TIMEOUT:-60}"
DIALECT="${DIALECT:-snowflake}"
colima_started=0

BUNDLES_DIR="${1:?usage: run_llm_verification_sqlsolver.sh BUNDLES_DIR REPORT_FILE}"
REPORT_FILE="${2:?REPORT_FILE is required}"

cleanup() {
  if [[ "$STOP_COLIMA" == "1" && "$colima_started" == "1" ]]; then
    colima stop --profile "$COLIMA_PROFILE"
  fi
}
trap cleanup EXIT

repo_relative() {
  local path
  path="$(cd "$(dirname "$1")" && pwd -P)/$(basename "$1")"
  case "$path" in
    "$QSEAL_DIR"/*) printf '/qseal/%s\n' "${path#"$QSEAL_DIR"/}" ;;
    *)
      echo "Path must be inside the QuerySeal repo: $path" >&2
      exit 2
      ;;
  esac
}

mkdir -p "$(dirname "$REPORT_FILE")"
touch "$REPORT_FILE"
CONTAINER_BUNDLES="$(repo_relative "$BUNDLES_DIR")"
CONTAINER_REPORT="$(repo_relative "$REPORT_FILE")"

echo "Starting Colima profile '$COLIMA_PROFILE' as x86_64..."
colima start --profile "$COLIMA_PROFILE" --arch x86_64 \
  --cpu "$COLIMA_CPUS" --memory "$COLIMA_MEMORY"
colima_started=1

if ! docker --context "colima-$COLIMA_PROFILE" image inspect "$SMOKE_IMAGE" >/dev/null 2>&1; then
  docker --context "colima-$COLIMA_PROFILE" build \
    -t "$SMOKE_IMAGE" \
    -f "$QSEAL_DIR/docker/sqlsolver-smoke.Dockerfile" \
    "$QSEAL_DIR"
fi

docker --context "colima-$COLIMA_PROFILE" run --rm -i \
  -e UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-/tmp/qseal-venv}" \
  -e UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/qseal-uv-cache}" \
  -e UV_LINK_MODE="${UV_LINK_MODE:-copy}" \
  -e CONTAINER_BUNDLES="$CONTAINER_BUNDLES" \
  -e CONTAINER_REPORT="$CONTAINER_REPORT" \
  -e SOLVER_TIMEOUT="$SOLVER_TIMEOUT" \
  -e DIALECT="$DIALECT" \
  -v "$SQLSOLVER_DIR:/sqlsolver" \
  -v "$QSEAL_DIR:/qseal" \
  -w /sqlsolver \
  "$SMOKE_IMAGE" \
  bash -lc '
    set -euo pipefail
    if [[ ! -f /sqlsolver/build/libs/sqlsolver-v1.1.0.jar ]]; then
      ./gradlew fatjar
    fi
    cd /qseal
    uv run --reinstall-package qseal python scripts/verify_llm_candidates.py "$CONTAINER_BUNDLES" \
      --dialect "$DIALECT" \
      --solver-command /qseal/scripts/sqlsolver_command.sh \
      --solver-timeout "$SOLVER_TIMEOUT" \
      --report-file "$CONTAINER_REPORT"
  '
echo "SQLSolver verification report: $REPORT_FILE"
