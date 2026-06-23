#!/usr/bin/env bash
# Build arm64 macOS Z3 Java bindings so SQLSolver runs natively on Apple Silicon.
#
# SQLSolver links Z3 through JNI. Its bundled native libraries are Linux
# x86-64 ELF, which is why the documented smoke path uses an x86 Colima
# container. To run SQLSolver natively on arm64 macOS you need a matching
# arm64 build of libz3java.dylib + libz3.dylib. Homebrew's z3 formula does not
# ship the Java binding, so this script builds Z3 4.13.0 (the release
# SQLSolver targets) from source with --java.
#
# Z3 4.13.0 has three latent source typos that trip the modern clang shipped
# with current Xcode; this script applies one-token fixes before building.
# The fixes do not change Z3 semantics, only correct member names that newer
# compilers no longer let through.
#
# Output:
#   $BUILD_DIR/libz3.dylib        arm64 Z3 core
#   $BUILD_DIR/libz3java.dylib    arm64 JNI bridge (loads libz3.dylib)
#   (the com.microsoft.z3 Java classes are reused from SQLSolver's bundled
#    z3-4.13.0.jar, so no matching jar is built here)
#
# Then run SQLSolver natively with scripts/run_sqlsolver_native.sh:
#   Z3_LIB_DIR="$OUT/build" SQLSOLVER_DIR=/path/SQLSolver \
#     scripts/run_sqlsolver_native.sh -sql1=a.sql -sql2=b.sql -schema=s.sql -print
set -euo pipefail

Z3_VERSION="${Z3_VERSION:-4.13.0}"
OUT="${OUT:-$(pwd)/z3java-$Z3_VERSION}"
JOBS="${JOBS:-$(sysctl -n hw.ncpu 2>/dev/null || echo 4)}"
JAVA_HOME="${JAVA_HOME:-}"

if [[ -z "$JAVA_HOME" ]]; then
  # Fall back to the homebrew JDK 17 if present.
  for cand in /opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home \
              /opt/homebrew/opt/openjdk/libexec/openjdk.jdk/Contents/Home; do
    if [[ -d "$cand" ]]; then JAVA_HOME="$cand"; break; fi
  done
fi
if [[ -z "${JAVA_HOME:-}" || ! -f "$JAVA_HOME/include/jni.h" ]]; then
  echo "JAVA_HOME must point at a JDK with JNI headers (jni.h)." >&2
  exit 2
fi
export JAVA_HOME

mkdir -p "$OUT"
SRC="$OUT/z3-$Z3_VERSION-src"
BUILD="$SRC/build"

if [[ ! -d "$SRC" ]]; then
  echo "Downloading Z3 $Z3_VERSION source..."
  curl -sL -o "$OUT/z3src.tar.gz" \
    "https://github.com/Z3Prover/z3/archive/refs/tags/z3-$Z3_VERSION.tar.gz"
  tar xzf "$OUT/z3src.tar.gz" -C "$OUT"
  mv "$OUT/z3-z3-$Z3_VERSION" "$SRC"
fi

echo "Patching latent 4.13.0 typos for modern clang..."
# column_info.h: member is m_lower_bound, not m_low_bound.
sed -i '' 's/c\.m_low_bound)/c.m_lower_bound)/' \
  "$SRC/src/math/lp/column_info.h"
# static_matrix.h: the getter is get_elem, not get.
sed -i '' 's/v\.m_matrix\.get(v\.m_row, v\.m_col)/v.m_matrix.get_elem(v.m_row, v.m_col)/' \
  "$SRC/src/math/lp/static_matrix.h"
# static_matrix_def.h: the column-cell accessor is get_val, not
# get_value_of_column_cell (the intended name is even left in a comment).
sed -i '' 's/A\.get_value_of_column_cell(col)/A.get_val(col)/' \
  "$SRC/src/math/lp/static_matrix_def.h"

cd "$SRC"
echo "Generating Makefile with --java..."
python3 scripts/mk_make.py --java

cd "$BUILD"
echo "Building (jobs=$JOBS)..."
make -j"$JOBS" libz3java.dylib

echo
echo "Done. arm64 Z3 Java bindings:"
ls -la "$BUILD/libz3.dylib" "$BUILD/libz3java.dylib"
echo
echo "Run SQLSolver natively with:"
echo "  Z3_LIB_DIR=\"$BUILD\" SQLSOLVER_DIR=/path/SQLSolver \\"
echo "    scripts/run_sqlsolver_native.sh -sql1=a.sql -sql2=b.sql -schema=s.sql -print"