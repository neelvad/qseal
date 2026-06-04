#!/usr/bin/env bash
set -euo pipefail

SQLSOLVER_DIR="${SQLSOLVER_DIR:-/sqlsolver}"
JAR_PATH="${JAR_PATH:-$SQLSOLVER_DIR/build/libs/sqlsolver-v1.1.0.jar}"
LIB_DIR="${LIB_DIR:-$SQLSOLVER_DIR/lib}"

if [[ ! -f "$JAR_PATH" ]]; then
  echo "SQLSolver jar not found: $JAR_PATH" >&2
  echo "Run ./gradlew fatjar inside $SQLSOLVER_DIR first." >&2
  exit 2
fi

if [[ ! -d "$LIB_DIR" ]]; then
  echo "SQLSolver native library directory not found: $LIB_DIR" >&2
  exit 2
fi

export LD_LIBRARY_PATH="$LIB_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

exec java -Djava.library.path="$LIB_DIR" -jar "$JAR_PATH" "$@"
