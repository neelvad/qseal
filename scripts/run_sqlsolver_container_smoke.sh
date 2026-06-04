#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SNOWPROVE_DIR="${SNOWPROVE_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
SQLSOLVER_DIR="${SQLSOLVER_DIR:-$HOME/workspace/snowprove-eval/SQLSolver}"
COLIMA_PROFILE="${COLIMA_PROFILE:-sqlsolver-x86}"
COLIMA_CPUS="${COLIMA_CPUS:-2}"
COLIMA_MEMORY="${COLIMA_MEMORY:-4}"
CASE_NAME="${CASE_NAME:-all}"
SMOKE_IMAGE="${SMOKE_IMAGE:-snowprove-sqlsolver-smoke:latest}"
REBUILD_IMAGE="${REBUILD_IMAGE:-0}"

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
docker --context "colima-$COLIMA_PROFILE" run --rm "${docker_tty_args[@]}" \
  -e CASE_NAME="$CASE_NAME" \
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
  '
