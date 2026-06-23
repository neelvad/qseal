# SQLSolver Spike

SQLSolver links Z3 through JNI. Its bundled native libraries
(`lib/libz3java.so`, `lib/libz3.so`) are Linux x86-64 ELF, which is why the
original smoke path uses an x86 Colima container (below). On Apple Silicon
you can instead build arm64 macOS Z3 Java bindings once and run SQLSolver
natively, with no container and no emulation overhead.

## Native arm64 macOS (Apple Silicon)

Homebrew's `z3` formula ships the C/Python `libz3.dylib` but not the Java
binding (`libz3java.dylib` + the `com.microsoft.z3` classes). So the native
path builds Z3 4.13.0 — the release SQLSolver targets — from source with
`--java`, then reuses SQLSolver's bundled `z3-4.13.0.jar` classes unchanged
(same release, so the JNI version handshake passes).

Build the bindings (needs a JDK with JNI headers, e.g. `openjdk@17`):

```bash
JAVA_HOME=$(/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home) \
  scripts/build_z3_java_native.sh
```

`scripts/build_z3_java_native.sh` downloads Z3 4.13.0, patches three latent
4.13.0 source typos that trip modern clang (one-token name fixes, no semantic
change), and builds `libz3.dylib` + `libz3java.dylib` under
`z3java-4.13.0/build/`.

Run SQLSolver natively through the wrapper (the native counterpart of
`sqlsolver_command.sh`, which sets `DYLD_LIBRARY_PATH` instead of
`LD_LIBRARY_PATH`):

```bash
Z3_LIB_DIR=z3java-4.13.0/build \
SQLSOLVER_DIR=/path/to/SQLSolver \
JAVA_BIN=$(/opt/homebrew/opt/openjdk@17/bin/java) \
  scripts/run_sqlsolver_native.sh -sql1=a.sql -sql2=b.sql -schema=s.sql -print
```

Observed native arm64 fixture results (matching the x86 container):

```text
redundant_distinct: EQ      (1057 ms)
unsafe_distinct:    NEQ     (418 ms)
unused_left_join:   EQ      (153 ms)
join_distinct_exists: EQ    (156 ms)
```

With the BIRD verdict funnel:

```bash
Z3_LIB_DIR=z3java-4.13.0/build SQLSOLVER_DIR=/path/to/SQLSolver \
  python scripts/probe_bird_verdict.py --pairs pairs.json --qed \
    --sqlsolver-command scripts/run_sqlsolver_native.sh \
    --verieql-dir /path/to/VeriEQL --report-file report.json
```

The rest of this document covers the x86 Colima container path, which remains
the fallback for x86 hosts or CI without an arm64 Z3 build.

## x86 Colima container

The shortest host-side smoke test is:

```bash
SQLSOLVER_DIR=/path/to/SQLSolver scripts/run_sqlsolver_container_smoke.sh
```

Set `SQLSOLVER_DIR` to a local SQLSolver checkout before running it. The script
starts the `sqlsolver-x86` Colima profile, builds a cached smoke-test image if
needed, builds the SQLSolver jar if needed, and runs all QuerySeal SQLSolver
compatibility cases plus a product-like `candidates run --verifier sqlsolver`
smoke test.
It also stops the Colima profile when the run exits. Set `STOP_COLIMA=0` if you
want to keep the profile running between smoke-test runs.
The container uses a throwaway uv environment and cache under `/tmp`, with
`UV_LINK_MODE=copy`, so it does not mutate the repo's macOS `.venv`.
Each run writes JSON artifacts under
`qseal-runs/sqlsolver-smoke/<timestamp>/`, which is ignored by git.

Useful overrides:

```bash
SQLSOLVER_DIR=/path/to/SQLSolver scripts/run_sqlsolver_container_smoke.sh
CASE_NAME=redundant_distinct scripts/run_sqlsolver_container_smoke.sh
RUN_CANDIDATE_SMOKE=0 scripts/run_sqlsolver_container_smoke.sh
RUN_FIXTURE_SMOKE=0 scripts/run_sqlsolver_container_smoke.sh
CANDIDATE_CASE_NAME=redundant_distinct scripts/run_sqlsolver_container_smoke.sh
COLIMA_CPUS=2 COLIMA_MEMORY=4 scripts/run_sqlsolver_container_smoke.sh
STOP_COLIMA=0 scripts/run_sqlsolver_container_smoke.sh
REBUILD_IMAGE=1 scripts/run_sqlsolver_container_smoke.sh
REPORT_DIR="$PWD/qseal-runs/manual" scripts/run_sqlsolver_container_smoke.sh
```

To check an arbitrary SQL pair, place the SQL and schema files inside the
QuerySeal repository and run:

```bash
SQLSOLVER_DIR=/path/to/SQLSolver \
RUN_FIXTURE_SMOKE=0 \
RUN_CANDIDATE_SMOKE=0 \
PAIR_ORIGINAL_PATH=qseal-runs/manual/original.sql \
PAIR_REWRITTEN_PATH=qseal-runs/manual/rewritten.sql \
PAIR_SCHEMA_PATH=qseal-runs/manual/schema.yml \
PAIR_DIALECT=duckdb \
REPORT_DIR="$PWD/qseal-runs/manual/sqlsolver" \
scripts/run_sqlsolver_container_smoke.sh
```

The result is written to `pair.verification.json`. Pair checks do not fail the
wrapper for `UNKNOWN`, `UNSUPPORTED`, or `NOT_EQUIVALENT`; the JSON status is
the compatibility result to inspect.

The first run builds `qseal-sqlsolver-smoke:latest`, which caches Java,
`file`, curl, and `uv`. Later runs reuse that image, so they skip `apt-get` and
the uv installer.

Start Colima:

```bash
colima start --profile sqlsolver-x86 --arch x86_64 --cpu 2 --memory 4
```

Run an Ubuntu shell with SQLSolver and QuerySeal mounted:

```bash
docker run --rm -it \
  -v /path/to/SQLSolver:/sqlsolver \
  -v /path/to/qseal:/qseal \
  -w /sqlsolver \
  ubuntu:22.04 \
  bash
```

Inside the container:

```bash
apt-get update
apt-get install -y openjdk-17-jdk ca-certificates curl
./gradlew fatjar

/qseal/scripts/run_sqlsolver_fixture.sh
CASE_NAME=all /qseal/scripts/run_sqlsolver_fixture.sh
CASE_NAME=unsafe_distinct /qseal/scripts/run_sqlsolver_fixture.sh
CASE_NAME=unused_left_join /qseal/scripts/run_sqlsolver_fixture.sh
CASE_NAME=fk_inner_join /qseal/scripts/run_sqlsolver_fixture.sh
```

The helper flattens each fixture query to one line because SQLSolver's CLI
treats corresponding lines in `-sql1` and `-sql2` as query pairs.

To exercise QuerySeal's SQLSolver backend end-to-end, install `uv` in the same
container and run the QuerySeal-facing fixture helper:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.local/bin/env

/qseal/scripts/run_qseal_sqlsolver_fixture.sh
CASE_NAME=all /qseal/scripts/run_qseal_sqlsolver_fixture.sh
CASE_NAME=redundant_distinct /qseal/scripts/run_qseal_sqlsolver_candidate_smoke.sh
```

That helper runs:

```bash
uv run qseal check \
  ORIGINAL.sql \
  REWRITTEN.sql \
  --schema /qseal/tests/fixtures/solver_compat/schema.yml \
  --verifier sqlsolver \
  --solver-command /qseal/scripts/sqlsolver_command.sh \
  --format json
```

Observed successful fixture results:

```text
redundant_distinct: EQ
unsafe_distinct: NEQ
unused_left_join: EQ
fk_inner_join: EQ
join_distinct_exists: EQ
```

`fk_inner_join` exercises FK-backed inner-join elimination. A 2026-06-18
x86_64 Colima run validated it both ways:

- QuerySeal backend artifact:
  `qseal-runs/sqlsolver-smoke/fk-inner-join-20260618/check/fk_inner_join.verification.json`
  reported `PROVEN_EQUIVALENT` with `SQLSolver returned EQ.`
- Direct SQLSolver fixture runner reported `Summary: [EQ]` in 3644 ms.

If `uname -m` prints `aarch64` while `file /sqlsolver/lib/libz3java.so` prints
`x86-64`, restart Colima with `--arch x86_64`.

## 2026-06-10 Premise Validation

Validated against the real solver (all compat cases plus manual pairs):

- `NOT NULL` column premises are consumed: redundant `IS NOT NULL` filter
  removal proves `EQ`, including under `GROUP BY` / `HAVING` / `COUNT(*)`.
- `PRIMARY KEY` (trusted unique + non-null) premises are consumed: DISTINCT
  removal and unused LEFT JOIN elimination prove `EQ`.
- Qualified relation names (`"db"."schema"."table"`) previously returned
  UNKNOWN because the generated DDL declares unqualified names. The backend
  now rewrites relations to their unqualified leaf names before solving, and
  refuses (UNSUPPORTED) when distinct qualified relations share a leaf name.
  The kestra not-null pair that returned UNKNOWN on 2026-06-09 now proves EQ.
