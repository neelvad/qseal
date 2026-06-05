#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SNOWPROVE_DIR="${SNOWPROVE_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
SQLSOLVER_DIR="${SQLSOLVER_DIR:-$HOME/workspace/snowprove-eval/SQLSolver}"
COLIMA_PROFILE="${COLIMA_PROFILE:-sqlsolver-x86}"
COLIMA_CPUS="${COLIMA_CPUS:-2}"
COLIMA_MEMORY="${COLIMA_MEMORY:-4}"
STOP_COLIMA="${STOP_COLIMA:-1}"
CASE_NAME="${CASE_NAME:-all}"
RUN_CANDIDATE_SMOKE="${RUN_CANDIDATE_SMOKE:-1}"
CANDIDATE_CASE_NAME="${CANDIDATE_CASE_NAME:-redundant_distinct}"
SMOKE_IMAGE="${SMOKE_IMAGE:-snowprove-sqlsolver-smoke:latest}"
REBUILD_IMAGE="${REBUILD_IMAGE:-0}"
REPORT_DIR="${REPORT_DIR:-$SNOWPROVE_DIR/snowprove-runs/sqlsolver-smoke/$(date -u +%Y%m%dT%H%M%SZ)}"
colima_started=0

cleanup() {
  if [[ "$STOP_COLIMA" == "1" && "$colima_started" == "1" ]]; then
    echo "Stopping Colima profile '$COLIMA_PROFILE'..."
    colima stop --profile "$COLIMA_PROFILE"
  fi
}

trap cleanup EXIT

if ! command -v colima >/dev/null 2>&1; then
  echo "colima is required. Install it with: brew install colima" >&2
  exit 2
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker CLI is required. Install Docker or Colima's Docker runtime first." >&2
  exit 2
fi

if [[ ! -d "$SQLSOLVER_DIR" ]]; then
  echo "SQLSolver directory not found: $SQLSOLVER_DIR" >&2
  echo "Set SQLSOLVER_DIR=/path/to/SQLSolver and rerun this script." >&2
  exit 2
fi

case "$REPORT_DIR" in
  "$SNOWPROVE_DIR"/*) CONTAINER_REPORT_DIR="/snowprove/${REPORT_DIR#"$SNOWPROVE_DIR"/}" ;;
  *)
    echo "REPORT_DIR must be inside the Snowprove repo: $SNOWPROVE_DIR" >&2
    exit 2
    ;;
esac

docker_tty_args=(-i)
if [[ -t 0 && -t 1 ]]; then
  docker_tty_args=(-it)
fi

echo "Starting Colima profile '$COLIMA_PROFILE' as x86_64..."
colima start \
  --profile "$COLIMA_PROFILE" \
  --arch x86_64 \
  --cpu "$COLIMA_CPUS" \
  --memory "$COLIMA_MEMORY"
colima_started=1

image_exists() {
  docker --context "colima-$COLIMA_PROFILE" image inspect "$SMOKE_IMAGE" >/dev/null 2>&1
}

if [[ "$REBUILD_IMAGE" == "1" ]] || ! image_exists; then
  echo "Building cached smoke-test image '$SMOKE_IMAGE'..."
  docker --context "colima-$COLIMA_PROFILE" build \
    -t "$SMOKE_IMAGE" \
    -f "$SNOWPROVE_DIR/docker/sqlsolver-smoke.Dockerfile" \
    "$SNOWPROVE_DIR"
fi

echo "Running Snowprove SQLSolver smoke test in $SMOKE_IMAGE..."
mkdir -p "$REPORT_DIR"
echo "Reports will be written to: $REPORT_DIR"
docker --context "colima-$COLIMA_PROFILE" run --rm "${docker_tty_args[@]}" \
  -e CASE_NAME="$CASE_NAME" \
  -e RUN_CANDIDATE_SMOKE="$RUN_CANDIDATE_SMOKE" \
  -e CANDIDATE_CASE_NAME="$CANDIDATE_CASE_NAME" \
  -e REPORT_DIR="$CONTAINER_REPORT_DIR" \
  -e UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-/tmp/snowprove-venv}" \
  -e UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/snowprove-uv-cache}" \
  -e UV_LINK_MODE="${UV_LINK_MODE:-copy}" \
  -v "$SQLSOLVER_DIR:/sqlsolver" \
  -v "$SNOWPROVE_DIR:/snowprove" \
  -w /sqlsolver \
  "$SMOKE_IMAGE" \
  bash -lc '
    set -euo pipefail

    if [[ ! -f /sqlsolver/build/libs/sqlsolver-v1.1.0.jar ]]; then
      ./gradlew fatjar
    fi

    CASE_NAME="$CASE_NAME" /snowprove/scripts/run_snowprove_sqlsolver_fixture.sh

    if [[ "$RUN_CANDIDATE_SMOKE" == "1" ]]; then
      CASE_NAME="$CANDIDATE_CASE_NAME" \
        /snowprove/scripts/run_snowprove_sqlsolver_candidate_smoke.sh
    fi
  '
