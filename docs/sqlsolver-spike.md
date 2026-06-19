# SQLSolver Spike

SQLSolver ships Linux native Z3 libraries, so run it in Ubuntu rather than
macOS directly.

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
