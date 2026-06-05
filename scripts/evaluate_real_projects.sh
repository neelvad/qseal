#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SNOWPROVE_DIR="${SNOWPROVE_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
CLONE_DIR="${CLONE_DIR:-/tmp/snowprove-real-projects}"
REPORT_ROOT="${REPORT_ROOT:-$SNOWPROVE_DIR/snowprove-runs/real-projects/$(date -u +%Y%m%dT%H%M%SZ)}"
RUN_COMPILED="${RUN_COMPILED:-0}"
DBT_PROFILES_DIR="${DBT_PROFILES_DIR:-$HOME/.dbt}"
REFRESH="${REFRESH:-0}"

PROJECT_SPECS=(
  "dbt-labs-jaffle-shop|https://github.com/dbt-labs/jaffle-shop.git|."
  "lightdash-jaffle-shop|https://github.com/lightdash/jaffle_shop.git|."
  "snowflake-dbt-demo-project|https://github.com/dpguthrie/snowflake-dbt-demo-project.git|."
  "fivetran-dbt-shopify|https://github.com/fivetran/dbt_shopify.git|."
  "calogica-dbt-expectations-integration|https://github.com/calogica/dbt-expectations.git|integration_tests"
)

usage() {
  cat <<'EOF'
Usage:
  scripts/evaluate_real_projects.sh

Environment overrides:
  CLONE_DIR=/tmp/snowprove-real-projects
  REPORT_ROOT=$PWD/snowprove-runs/real-projects/manual
  REFRESH=1                 Re-clone each project under CLONE_DIR.
  RUN_COMPILED=1            Try dbt deps/compile and scan compiled SQL.
  DBT_PROFILES_DIR=$HOME/.dbt

Outputs:
  REPORT_ROOT/<project>/raw-report.json
  REPORT_ROOT/<project>/raw-output.txt
  REPORT_ROOT/<project>/raw-patches/
  REPORT_ROOT/<project>/compiled-report.json       when RUN_COMPILED=1 succeeds
  REPORT_ROOT/<project>/compiled-output.txt        when RUN_COMPILED=1 succeeds
  REPORT_ROOT/<project>/compiled-patches/          when RUN_COMPILED=1 succeeds
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

if ! command -v git >/dev/null 2>&1; then
  echo "git is required." >&2
  exit 2
fi

mkdir -p "$CLONE_DIR" "$REPORT_ROOT"

snowprove() {
  UV_CACHE_DIR="${UV_CACHE_DIR:-$SNOWPROVE_DIR/.uv-cache}" \
    uv run --project "$SNOWPROVE_DIR" snowprove "$@"
}

clone_project() {
  local name="$1"
  local url="$2"
  local repo_dir="$CLONE_DIR/$name"

  if [[ "$REFRESH" == "1" && -d "$repo_dir" ]]; then
    rm -rf "$repo_dir"
  fi

  if [[ ! -d "$repo_dir/.git" ]]; then
    echo "Cloning $url -> $repo_dir"
    git clone --depth 1 "$url" "$repo_dir"
  else
    echo "Using existing clone: $repo_dir"
  fi
}

run_raw_scan() {
  local name="$1"
  local scan_dir="$2"
  local report_dir="$REPORT_ROOT/$name"

  mkdir -p "$report_dir"
  echo "Raw scan: $scan_dir"
  snowprove dbt scan "$scan_dir" \
    --all \
    --report-file "$report_dir/raw-report.json" \
    --write-patches "$report_dir/raw-patches" \
    > "$report_dir/raw-output.txt" 2>&1 || {
      echo "Skipping remaining raw scan work for $name: snowprove raw scan failed." \
        | tee "$report_dir/raw-skipped.txt"
      return
    }
}

run_compiled_scan() {
  local name="$1"
  local scan_dir="$2"
  local report_dir="$REPORT_ROOT/$name"

  if [[ "$RUN_COMPILED" != "1" ]]; then
    return
  fi

  if ! command -v dbt >/dev/null 2>&1; then
    echo "Skipping compiled scan for $name: dbt command not found." \
      | tee "$report_dir/compiled-skipped.txt"
    return
  fi

  if [[ ! -d "$DBT_PROFILES_DIR" ]]; then
    echo "Skipping compiled scan for $name: DBT_PROFILES_DIR not found: $DBT_PROFILES_DIR" \
      | tee "$report_dir/compiled-skipped.txt"
    return
  fi

  echo "Compiled scan: $scan_dir"
  (
    cd "$scan_dir"
    dbt deps --profiles-dir "$DBT_PROFILES_DIR"
    dbt compile --profiles-dir "$DBT_PROFILES_DIR"
  ) > "$report_dir/dbt-compile-output.txt" 2>&1 || {
    echo "Skipping compiled scan for $name: dbt compile failed." \
      | tee "$report_dir/compiled-skipped.txt"
    return
  }

  snowprove dbt scan "$scan_dir" \
    --use-compiled \
    --all \
    --report-file "$report_dir/compiled-report.json" \
    --write-patches "$report_dir/compiled-patches" \
    > "$report_dir/compiled-output.txt" 2>&1 || {
      echo "Skipping compiled scan for $name: snowprove compiled scan failed." \
        | tee "$report_dir/compiled-skipped.txt"
      return
    }
}

for spec in "${PROJECT_SPECS[@]}"; do
  IFS="|" read -r name url subdir <<< "$spec"
  repo_dir="$CLONE_DIR/$name"
  scan_dir="$repo_dir/$subdir"

  echo
  echo "== $name =="
  clone_project "$name" "$url"

  if [[ ! -d "$scan_dir" ]]; then
    echo "Skipping $name: scan directory not found: $scan_dir" >&2
    continue
  fi

  run_raw_scan "$name" "$scan_dir"
  run_compiled_scan "$name" "$scan_dir"
done

echo
echo "Reports written to: $REPORT_ROOT"
