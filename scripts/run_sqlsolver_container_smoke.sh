#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QSEAL_DIR="${QSEAL_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
SQLSOLVER_DIR="${SQLSOLVER_DIR:-$HOME/workspace/qseal-eval/SQLSolver}"
COLIMA_PROFILE="${COLIMA_PROFILE:-sqlsolver-x86}"
COLIMA_CPUS="${COLIMA_CPUS:-2}"
COLIMA_MEMORY="${COLIMA_MEMORY:-4}"
STOP_COLIMA="${STOP_COLIMA:-1}"
CASE_NAME="${CASE_NAME:-all}"
RUN_FIXTURE_SMOKE="${RUN_FIXTURE_SMOKE:-1}"
RUN_CANDIDATE_SMOKE="${RUN_CANDIDATE_SMOKE:-1}"
CANDIDATE_CASE_NAME="${CANDIDATE_CASE_NAME:-redundant_distinct}"
PAIR_ORIGINAL_PATH="${PAIR_ORIGINAL_PATH:-}"
PAIR_REWRITTEN_PATH="${PAIR_REWRITTEN_PATH:-}"
PAIR_SCHEMA_PATH="${PAIR_SCHEMA_PATH:-}"
PAIR_SCHEMA_FORMAT="${PAIR_SCHEMA_FORMAT:-auto}"
PAIR_DIALECT="${PAIR_DIALECT:-snowflake}"
SMOKE_IMAGE="${SMOKE_IMAGE:-qseal-sqlsolver-smoke:latest}"
REBUILD_IMAGE="${REBUILD_IMAGE:-0}"
REPORT_DIR="${REPORT_DIR:-$QSEAL_DIR/qseal-runs/sqlsolver-smoke/$(date -u +%Y%m%dT%H%M%SZ)}"
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
  "$QSEAL_DIR"/*) CONTAINER_REPORT_DIR="/qseal/${REPORT_DIR#"$QSEAL_DIR"/}" ;;
  *)
    echo "REPORT_DIR must be inside the QuerySeal repo: $QSEAL_DIR" >&2
    exit 2
    ;;
esac

repo_container_path() {
  local path="$1"
  local absolute_path

  if [[ ! -f "$path" && ! -f "$QSEAL_DIR/$path" ]]; then
    echo "Pair input not found: $path" >&2
    exit 2
  fi

  if [[ "$path" != /* ]]; then
    path="$QSEAL_DIR/$path"
  fi
  absolute_path="$(cd "$(dirname "$path")" && pwd -P)/$(basename "$path")"

  case "$absolute_path" in
    "$QSEAL_DIR"/*) printf '/qseal/%s\n' "${absolute_path#"$QSEAL_DIR"/}" ;;
    *)
      echo "Pair input must be inside the QuerySeal repo: $absolute_path" >&2
      exit 2
      ;;
  esac
}

pair_paths=("$PAIR_ORIGINAL_PATH" "$PAIR_REWRITTEN_PATH" "$PAIR_SCHEMA_PATH")
pair_path_count=0
for path in "${pair_paths[@]}"; do
  if [[ -n "$path" ]]; then
    pair_path_count=$((pair_path_count + 1))
  fi
done

if [[ "$pair_path_count" != "0" && "$pair_path_count" != "3" ]]; then
  echo "Set PAIR_ORIGINAL_PATH, PAIR_REWRITTEN_PATH, and PAIR_SCHEMA_PATH together." >&2
  exit 2
fi

if [[ "$pair_path_count" == "3" ]]; then
  CONTAINER_PAIR_ORIGINAL_PATH="$(repo_container_path "$PAIR_ORIGINAL_PATH")"
  CONTAINER_PAIR_REWRITTEN_PATH="$(repo_container_path "$PAIR_REWRITTEN_PATH")"
  CONTAINER_PAIR_SCHEMA_PATH="$(repo_container_path "$PAIR_SCHEMA_PATH")"
else
  CONTAINER_PAIR_ORIGINAL_PATH=""
  CONTAINER_PAIR_REWRITTEN_PATH=""
  CONTAINER_PAIR_SCHEMA_PATH=""
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
colima_started=1

image_exists() {
  docker --context "colima-$COLIMA_PROFILE" image inspect "$SMOKE_IMAGE" >/dev/null 2>&1
}

if [[ "$REBUILD_IMAGE" == "1" ]] || ! image_exists; then
  echo "Building cached smoke-test image '$SMOKE_IMAGE'..."
  docker --context "colima-$COLIMA_PROFILE" build \
    -t "$SMOKE_IMAGE" \
    -f "$QSEAL_DIR/docker/sqlsolver-smoke.Dockerfile" \
    "$QSEAL_DIR"
fi

echo "Running QuerySeal SQLSolver smoke test in $SMOKE_IMAGE..."
mkdir -p "$REPORT_DIR"
echo "Reports will be written to: $REPORT_DIR"
docker --context "colima-$COLIMA_PROFILE" run --rm "${docker_tty_args[@]}" \
  -e CASE_NAME="$CASE_NAME" \
  -e RUN_FIXTURE_SMOKE="$RUN_FIXTURE_SMOKE" \
  -e RUN_CANDIDATE_SMOKE="$RUN_CANDIDATE_SMOKE" \
  -e CANDIDATE_CASE_NAME="$CANDIDATE_CASE_NAME" \
  -e PAIR_ORIGINAL_PATH="$CONTAINER_PAIR_ORIGINAL_PATH" \
  -e PAIR_REWRITTEN_PATH="$CONTAINER_PAIR_REWRITTEN_PATH" \
  -e PAIR_SCHEMA_PATH="$CONTAINER_PAIR_SCHEMA_PATH" \
  -e PAIR_SCHEMA_FORMAT="$PAIR_SCHEMA_FORMAT" \
  -e PAIR_DIALECT="$PAIR_DIALECT" \
  -e REPORT_DIR="$CONTAINER_REPORT_DIR" \
  -e UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-/tmp/qseal-venv}" \
  -e UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/qseal-uv-cache}" \
  -e UV_LINK_MODE="${UV_LINK_MODE:-copy}" \
  -v "$SQLSOLVER_DIR:/sqlsolver" \
  -v "$QSEAL_DIR:/qseal" \
  -w /sqlsolver \
  "$SMOKE_IMAGE" \
  bash -lc '
    set -euo pipefail

    if [[ ! -f /sqlsolver/build/libs/sqlsolver-v1.1.0.jar ]]; then
      ./gradlew fatjar
    fi

    if [[ "$RUN_FIXTURE_SMOKE" == "1" ]]; then
      CASE_NAME="$CASE_NAME" /qseal/scripts/run_qseal_sqlsolver_fixture.sh
    fi

    if [[ "$RUN_CANDIDATE_SMOKE" == "1" ]]; then
      CASE_NAME="$CANDIDATE_CASE_NAME" \
        /qseal/scripts/run_qseal_sqlsolver_candidate_smoke.sh
    fi

    if [[ -n "$PAIR_ORIGINAL_PATH" ]]; then
      /qseal/scripts/run_qseal_sqlsolver_pair.sh
    fi
  '
