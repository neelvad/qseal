#!/usr/bin/env bash
# Run the VeriEQL refuter spike against a local VeriEQL checkout.
#
# VeriEQL is licensed CC BY-NC-SA 4.0 (NonCommercial). QuerySeal does not
# bundle or depend on it; this script only drives a user-supplied checkout.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERIEQL_DIR="${VERIEQL_DIR:-}"

if [[ -z "$VERIEQL_DIR" ]]; then
  echo "VERIEQL_DIR is required." >&2
  echo "Clone https://github.com/VeriEQL/VeriEQL and set VERIEQL_DIR." >&2
  exit 2
fi

if [[ ! -d "$VERIEQL_DIR" ]]; then
  echo "VeriEQL checkout not found: $VERIEQL_DIR" >&2
  echo "Clone https://github.com/VeriEQL/VeriEQL and set VERIEQL_DIR." >&2
  exit 2
fi

if [[ ! -x "$VERIEQL_DIR/.venv/bin/python" ]]; then
  echo "Creating VeriEQL virtualenv (python 3.11, pinned z3 4.12.2)..."
  (
    cd "$VERIEQL_DIR"
    uv venv --python 3.11 .venv
    UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-verieql}" uv pip install \
      -r requirements.txt 'z3-solver==4.12.2.0' 'setuptools<81' \
      --python .venv/bin/python
    # VeriEQL requires its patched z3py modules (ctx-aware And/Or wrappers).
    cp z3py_libs/*.py .venv/lib/python3.11/site-packages/z3/
  )
fi

cd "$VERIEQL_DIR"
exec env PYTHONPATH="$VERIEQL_DIR" .venv/bin/python "$SCRIPT_DIR/verieql_spike.py"
