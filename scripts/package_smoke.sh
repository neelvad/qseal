#!/usr/bin/env bash
set -euo pipefail

DIST_DIR="${DIST_DIR:-dist}"
PYTHON_BIN="${PYTHON_BIN:-python}"

if [[ ! -d "$DIST_DIR" ]]; then
  echo "Distribution directory not found: $DIST_DIR" >&2
  exit 2
fi

stale_dist_count="$(find "$DIST_DIR" -maxdepth 1 -type f -iname '*snowprove*' | wc -l | tr -d ' ')"
if [[ "$stale_dist_count" -ne 0 ]]; then
  echo "Distribution directory contains stale snowprove artifacts." >&2
  find "$DIST_DIR" -maxdepth 1 -type f -iname '*snowprove*' >&2
  exit 2
fi

wheel_count="$(find "$DIST_DIR" -maxdepth 1 -type f -name 'qseal-*.whl' | wc -l | tr -d ' ')"
sdist_count="$(find "$DIST_DIR" -maxdepth 1 -type f -name 'qseal-*.tar.gz' | wc -l | tr -d ' ')"

if [[ "$wheel_count" -ne 1 ]]; then
  echo "Expected exactly one qseal wheel in $DIST_DIR; found $wheel_count." >&2
  exit 2
fi
if [[ "$sdist_count" -ne 1 ]]; then
  echo "Expected exactly one qseal source distribution in $DIST_DIR; found $sdist_count." >&2
  exit 2
fi

wheel="$(find "$DIST_DIR" -maxdepth 1 -type f -name 'qseal-*.whl' | sort | head -n 1)"
sdist="$(find "$DIST_DIR" -maxdepth 1 -type f -name 'qseal-*.tar.gz' | sort | head -n 1)"

"$PYTHON_BIN" - "$wheel" "$sdist" <<'PY'
from __future__ import annotations

import configparser
import sys
import tarfile
import zipfile
from pathlib import PurePosixPath

wheel_path, sdist_path = sys.argv[1:]

with zipfile.ZipFile(wheel_path) as wheel:
    wheel_names = wheel.namelist()
    stale = [name for name in wheel_names if "snowprove" in name.lower()]
    if stale:
        raise SystemExit(f"wheel contains stale snowprove paths: {stale[:5]}")
    entry_points = [
        name for name in wheel_names if name.endswith(".dist-info/entry_points.txt")
    ]
    if len(entry_points) != 1:
        raise SystemExit(f"expected one entry_points.txt, found {entry_points}")
    parser = configparser.ConfigParser()
    parser.read_string(wheel.read(entry_points[0]).decode())
    scripts = dict(parser.items("console_scripts"))
    if scripts != {"qseal": "qseal.cli:main"}:
        raise SystemExit(f"unexpected console scripts: {scripts}")

blocked_roots = {
    ".claude",
    ".pytest_cache",
    ".ruff_cache",
    ".uv-cache",
    ".venv",
    "build",
    "dist",
    "qseal-runs",
}
with tarfile.open(sdist_path, "r:gz") as sdist:
    sdist_names = sdist.getnames()
    stale = [name for name in sdist_names if "snowprove" in name.lower()]
    if stale:
        raise SystemExit(f"sdist contains stale snowprove paths: {stale[:5]}")
    leaked = []
    for name in sdist_names:
        parts = PurePosixPath(name).parts
        if len(parts) > 1 and parts[1] in blocked_roots:
            leaked.append(name)
    if leaked:
        raise SystemExit(f"sdist contains local-only files: {leaked[:5]}")

print(f"Artifacts inspected: {wheel_path}, {sdist_path}")
PY

smoke_root="${SMOKE_ROOT:-$(mktemp -d "${TMPDIR:-/tmp}/qseal-package-smoke.XXXXXX")}"
cleanup_smoke_root=0
if [[ -z "${SMOKE_ROOT:-}" ]]; then
  cleanup_smoke_root=1
fi
cleanup() {
  if [[ "$cleanup_smoke_root" == "1" ]]; then
    rm -rf "$smoke_root"
  fi
}
trap cleanup EXIT

venv="$smoke_root/venv"
"$PYTHON_BIN" -m venv "$venv"

if command -v uv >/dev/null 2>&1; then
  uv pip install --python "$venv/bin/python" "$wheel"
else
  "$venv/bin/python" -m pip install "$wheel"
fi

project="$smoke_root/dbt_project"
mkdir -p "$project/models"
cat > "$project/models/dim_users.sql" <<'SQL'
SELECT DISTINCT user_id FROM dim_users
SQL
cat > "$project/models/schema.yml" <<'YAML'
version: 2
models:
  - name: dim_users
    columns:
      - name: user_id
        tests:
          - unique
          - not_null
YAML

query="$smoke_root/query.sql"
schema="$smoke_root/schema.yml"
cat > "$query" <<'SQL'
SELECT DISTINCT user_id FROM users
SQL
cat > "$schema" <<'YAML'
tables:
  users:
    columns:
      user_id:
        nullable: false
    unique:
      - [user_id]
YAML

(
  cd "$smoke_root"
  "$venv/bin/qseal" --help >/dev/null
  "$venv/bin/qseal" dbt intake --help >/dev/null
  "$venv/bin/qseal" dbt intake "$project" --format json > intake.json
  "$venv/bin/qseal" suggest "$query" --schema "$schema" --all --format json > suggestion.json
  "$venv/bin/python" - <<'PY'
from __future__ import annotations

import json
from pathlib import Path

from qseal.corpora import bundled_corpus_path

corpus_path = bundled_corpus_path()
if corpus_path.name != "corpus.yml" or corpus_path.parent.name != "duckdb-v1":
    raise SystemExit(f"unexpected bundled corpus path: {corpus_path}")

intake = json.loads(Path("intake.json").read_text())
if intake["artifact_type"] != "dbt_intake":
    raise SystemExit(f"unexpected intake artifact: {intake}")
if intake["summary"]["proven_finding_count"] != 1:
    raise SystemExit(f"unexpected intake finding count: {intake['summary']}")
if "SELECT" in Path("intake.json").read_text().upper():
    raise SystemExit("intake artifact leaked SQL text")

suggestion = json.loads(Path("suggestion.json").read_text())
if suggestion["results"][0]["status"] != "PROVEN_EQUIVALENT":
    raise SystemExit(f"unexpected suggestion result: {suggestion}")

print("Installed wheel smoke passed.")
PY
)
