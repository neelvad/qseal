#!/usr/bin/env bash
# Run SQLSolver natively on arm64 macOS against locally built Z3 Java bindings.
#
# SQLSolver links Z3 through JNI. Its bundled native libraries
# (lib/libz3java.so, lib/libz3.so) are Linux x86-64 ELF, so on Apple Silicon
# you need an arm64 macOS build of the Z3 Java bindings (libz3java.dylib +
# libz3.dylib). Build them once with scripts/build_z3_java_native.sh, then
# point this wrapper at the build dir. The bundled z3-4.13.0.jar Java classes
# are reused unchanged because the native build targets the same Z3 release.
#
# This is the native counterpart of scripts/sqlsolver_command.sh, which sets
# LD_LIBRARY_PATH for the Linux/x86 container path.
#
# Required env:
#   Z3_LIB_DIR      dir containing libz3java.dylib + libz3.dylib
#   SQLSOLVER_DIR   SQLSolver checkout (jar built with ./gradlew fatjar)
# Optional env:
#   JAVA_BIN        java binary (default: java on PATH; needs JDK 17+)
#   JAR_PATH        override the jar path
#
# Example (with the BIRD verdict funnel):
#   Z3_LIB_DIR=$HOME/z3java-build SQLSOLVER_DIR=$HOME/SQLSolver \
#     python scripts/probe_bird_verdict.py --pairs pairs.json --qed \
#       --sqlsolver-command scripts/run_sqlsolver_native.sh \
#       --verieql-dir $HOME/VeriEQL --report-file report.json
set -euo pipefail

if [[ -z "${Z3_LIB_DIR:-}" ]]; then
  echo "Z3_LIB_DIR is required (dir with libz3java.dylib + libz3.dylib)" >&2
  exit 2
fi
SQLSOLVER_DIR="${SQLSOLVER_DIR:?SQLSOLVER_DIR is required (SQLSolver checkout)}"
JAVA_BIN="${JAVA_BIN:-java}"
JAR_PATH="${JAR_PATH:-$SQLSOLVER_DIR/build/libs/sqlsolver-v1.1.0.jar}"

if [[ ! -f "$JAR_PATH" ]]; then
  echo "SQLSolver jar not found: $JAR_PATH" >&2
  echo "Run ./gradlew fatjar inside $SQLSOLVER_DIR first." >&2
  exit 2
fi
if [[ ! -f "$Z3_LIB_DIR/libz3java.dylib" ]]; then
  echo "libz3java.dylib not found in Z3_LIB_DIR: $Z3_LIB_DIR" >&2
  echo "Build the arm64 Z3 Java bindings with scripts/build_z3_java_native.sh." >&2
  exit 2
fi

export DYLD_LIBRARY_PATH="$Z3_LIB_DIR${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}"

exec "$JAVA_BIN" -Djava.library.path="$Z3_LIB_DIR" -jar "$JAR_PATH" "$@"