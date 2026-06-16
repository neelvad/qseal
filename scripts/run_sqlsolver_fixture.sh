#!/usr/bin/env bash
set -euo pipefail

CASE_NAME="${CASE_NAME:-redundant_distinct}"
QSEAL_DIR="${QSEAL_DIR:-${SNOWPROVE_DIR:-/qseal}}"
SQLSOLVER_DIR="${SQLSOLVER_DIR:-/sqlsolver}"
RUN_DIR="${RUN_DIR:-/tmp/sqlsolver-run}"
JAR_PATH="${JAR_PATH:-$SQLSOLVER_DIR/build/libs/sqlsolver-v1.1.0.jar}"
LIB_DIR="${LIB_DIR:-$SQLSOLVER_DIR/lib}"
CASES_MANIFEST="$QSEAL_DIR/tests/fixtures/solver_compat/cases.yml"

normalize_sql() {
  sed -e 's/--.*$//' -e 's/[[:space:]]\+/ /g' "$1" \
    | awk 'NF { printf "%s ", $0 } END { print "" }' \
    | sed -e 's/^ *//' -e 's/ *$//' -e 's/;$//'
}

case_names() {
  if [[ "$CASE_NAME" != "all" ]]; then
    echo "$CASE_NAME"
    return
  fi

  awk '/^[[:space:]]*- name:/ { print $3 }' "$CASES_MANIFEST"
}

require_sqlsolver() {
  if [[ ! -d "$SQLSOLVER_DIR" ]]; then
    echo "SQLSolver directory not found: $SQLSOLVER_DIR" >&2
    exit 2
  fi

  if [[ ! -f "$JAR_PATH" ]]; then
    echo "SQLSolver jar not found: $JAR_PATH" >&2
    echo "Run ./gradlew fatjar inside $SQLSOLVER_DIR first." >&2
    exit 2
  fi
}

write_schema() {
  local schema_path="$1"
  cat > "$schema_path" <<'SQL'
CREATE TABLE users (
  user_id INT PRIMARY KEY,
  status VARCHAR(255)
);

CREATE TABLE dim_users (
  user_id INT PRIMARY KEY
);

CREATE TABLE fact_orders (
  user_id INT,
  revenue INT
);

CREATE TABLE orders (
  user_id INT
);
SQL
}

print_environment() {
  echo "Architecture: $(uname -m)"
  echo "SQLSolver jar: $JAR_PATH"
  echo "SQLSolver libs:"
  if command -v file >/dev/null 2>&1; then
    file "$LIB_DIR/libz3java.so" "$LIB_DIR/libz3.so" || true
  else
    echo "file command not installed; skipping native library diagnostics."
  fi
}

run_case() {
  local name="$1"
  local case_dir="$QSEAL_DIR/tests/fixtures/solver_compat/$name"
  local case_run_dir="$RUN_DIR/$name"
  local schema_path="$case_run_dir/schema.sql"

  if [[ ! -d "$case_dir" ]]; then
    echo "Fixture case not found: $case_dir" >&2
    exit 2
  fi

  mkdir -p "$case_run_dir"
  normalize_sql "$case_dir/original.sql" > "$case_run_dir/sql1.sql"
  normalize_sql "$case_dir/rewritten.sql" > "$case_run_dir/sql2.sql"
  write_schema "$schema_path"

  echo
  echo "Case: $name"
  echo "SQL 1: $(cat "$case_run_dir/sql1.sql")"
  echo "SQL 2: $(cat "$case_run_dir/sql2.sql")"

  local output
  output=$(
    java -Djava.library.path="$LIB_DIR" \
      -jar "$JAR_PATH" \
      -sql1="$case_run_dir/sql1.sql" \
      -sql2="$case_run_dir/sql2.sql" \
      -schema="$schema_path" \
      -print
  )
  echo "$output"
  echo "Summary: $(echo "$output" | tail -n 1)"
}

require_sqlsolver
print_environment

export LD_LIBRARY_PATH="$LIB_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

for name in $(case_names); do
  run_case "$name"
done
