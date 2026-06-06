#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SNOWPROVE_DIR="${SNOWPROVE_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
CLONE_DIR="${CLONE_DIR:-/tmp/snowprove-real-projects}"
REPORT_ROOT="${REPORT_ROOT:-$SNOWPROVE_DIR/snowprove-runs/real-projects/$(date -u +%Y%m%dT%H%M%SZ)}"
RUN_COMPILED="${RUN_COMPILED:-0}"
DBT_PROFILES_DIR="${DBT_PROFILES_DIR:-$HOME/.dbt}"
DUCKDB_DBT_COMMAND="${DUCKDB_DBT_COMMAND:-uvx --from dbt-duckdb dbt}"
PROJECT_FILTER="${PROJECT_FILTER:-}"
REFRESH="${REFRESH:-0}"

PROJECT_SPECS=(
  "dbt-labs-jaffle-shop|https://github.com/dbt-labs/jaffle-shop.git|.|default"
  "dbt-labs-jaffle-shop-duckdb|https://github.com/dbt-labs/jaffle_shop_duckdb.git|.|duckdb"
  "kestra-dbt-demo|https://github.com/kestra-io/dbt-demo.git|.|duckdb"
  "lightdash-jaffle-shop|https://github.com/lightdash/jaffle_shop.git|.|default"
  "snowflake-dbt-demo-project|https://github.com/dpguthrie/snowflake-dbt-demo-project.git|.|default"
  "fivetran-dbt-shopify|https://github.com/fivetran/dbt_shopify.git|.|default"
  "calogica-dbt-expectations-integration|https://github.com/calogica/dbt-expectations.git|integration_tests|default"
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
  DUCKDB_DBT_COMMAND="uvx --from dbt-duckdb dbt"
  PROJECT_FILTER=duckdb       Only run projects whose name contains this value.

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
  local profile_kind="$3"
  local report_dir="$REPORT_ROOT/$name"
  local profiles_dir="$DBT_PROFILES_DIR"
  local dbt_command=(dbt)

  if [[ "$RUN_COMPILED" != "1" ]]; then
    return
  fi

  if [[ "$profile_kind" == "duckdb" ]]; then
    profiles_dir="$report_dir/dbt-profiles"
    write_duckdb_profile "$scan_dir" "$profiles_dir" "$report_dir/$name.duckdb"
    # shellcheck disable=SC2206
    dbt_command=($DUCKDB_DBT_COMMAND)
  elif ! command -v dbt >/dev/null 2>&1; then
    echo "Skipping compiled scan for $name: dbt command not found." \
      | tee "$report_dir/compiled-skipped.txt"
    return
  fi

  if [[ ! -d "$profiles_dir" ]]; then
    echo "Skipping compiled scan for $name: profiles dir not found: $profiles_dir" \
      | tee "$report_dir/compiled-skipped.txt"
    return
  fi

  echo "Compiled scan: $scan_dir"
  (
    cd "$scan_dir"
    "${dbt_command[@]}" deps --profiles-dir "$profiles_dir"
    "${dbt_command[@]}" compile --profiles-dir "$profiles_dir"
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

write_duckdb_profile() {
  local project_dir="$1"
  local profiles_dir="$2"
  local duckdb_path="$3"
  local profile_name

  profile_name="$(project_profile_name "$project_dir")"
  mkdir -p "$profiles_dir"
  cat > "$profiles_dir/profiles.yml" <<YAML
$profile_name:
  target: dev
  outputs:
    dev:
      type: duckdb
      path: "$duckdb_path"
YAML
}

project_profile_name() {
  local project_dir="$1"
  local project_file="$project_dir/dbt_project.yml"
  local profile
  local name

  profile="$(awk -F: '/^[[:space:]]*profile:/ { gsub(/[ "'\''"]/, "", $2); print $2; exit }' "$project_file" 2>/dev/null || true)"
  if [[ -n "$profile" ]]; then
    echo "$profile"
    return
  fi

  name="$(awk -F: '/^[[:space:]]*name:/ { gsub(/[ "'\''"]/, "", $2); print $2; exit }' "$project_file" 2>/dev/null || true)"
  if [[ -n "$name" ]]; then
    echo "$name"
    return
  fi

  echo "snowprove_duckdb"
}

for spec in "${PROJECT_SPECS[@]}"; do
  IFS="|" read -r name url subdir profile_kind <<< "$spec"
  repo_dir="$CLONE_DIR/$name"
  scan_dir="$repo_dir/$subdir"

  if [[ -n "$PROJECT_FILTER" && "$name" != *"$PROJECT_FILTER"* ]]; then
    continue
  fi

  echo
  echo "== $name =="
  clone_project "$name" "$url"

  if [[ ! -d "$scan_dir" ]]; then
    echo "Skipping $name: scan directory not found: $scan_dir" >&2
    continue
  fi

  run_raw_scan "$name" "$scan_dir"
  run_compiled_scan "$name" "$scan_dir" "$profile_kind"
done

echo
echo "Reports written to: $REPORT_ROOT"
