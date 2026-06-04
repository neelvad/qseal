# SQLSolver Spike

SQLSolver ships Linux native Z3 libraries, so run it in Ubuntu rather than
macOS directly.

The shortest host-side smoke test is:

```bash
scripts/run_sqlsolver_container_smoke.sh
```

By default it expects SQLSolver at `~/workspace/snowprove-eval/SQLSolver`, starts
the `sqlsolver-x86` Colima profile, builds the SQLSolver jar if needed, installs
container prerequisites, and runs all Snowprove SQLSolver compatibility cases.
The container uses a throwaway uv environment and cache under `/tmp`, with
`UV_LINK_MODE=copy`, so it does not mutate the repo's macOS `.venv`.

Useful overrides:

```bash
SQLSOLVER_DIR=/path/to/SQLSolver scripts/run_sqlsolver_container_smoke.sh
CASE_NAME=redundant_distinct scripts/run_sqlsolver_container_smoke.sh
COLIMA_CPUS=2 COLIMA_MEMORY=4 scripts/run_sqlsolver_container_smoke.sh
```

Start Colima:

```bash
colima start --profile sqlsolver-x86 --arch x86_64 --cpu 2 --memory 4
```

Run an Ubuntu shell with SQLSolver and Snowprove mounted:

```bash
docker run --rm -it \
  -v ~/workspace/snowprove-eval/SQLSolver:/sqlsolver \
  -v ~/workspace/snowprove:/snowprove \
  -w /sqlsolver \
  ubuntu:22.04 \
  bash
```

Inside the container:

```bash
apt-get update
apt-get install -y openjdk-17-jdk ca-certificates curl
./gradlew fatjar

/snowprove/scripts/run_sqlsolver_fixture.sh
CASE_NAME=all /snowprove/scripts/run_sqlsolver_fixture.sh
CASE_NAME=unsafe_distinct /snowprove/scripts/run_sqlsolver_fixture.sh
CASE_NAME=unused_left_join /snowprove/scripts/run_sqlsolver_fixture.sh
```

The helper flattens each fixture query to one line because SQLSolver's CLI
treats corresponding lines in `-sql1` and `-sql2` as query pairs.

To exercise Snowprove's SQLSolver backend end-to-end, install `uv` in the same
container and run the Snowprove-facing fixture helper:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.local/bin/env

/snowprove/scripts/run_snowprove_sqlsolver_fixture.sh
CASE_NAME=all /snowprove/scripts/run_snowprove_sqlsolver_fixture.sh
```

That helper runs:

```bash
uv run snowprove check \
  ORIGINAL.sql \
  REWRITTEN.sql \
  --schema /snowprove/tests/fixtures/solver_compat/schema.yml \
  --verifier sqlsolver \
  --solver-command /snowprove/scripts/sqlsolver_command.sh \
  --format json
```

Observed successful fixture results:

```text
redundant_distinct: EQ
unsafe_distinct: NEQ
unused_left_join: EQ
join_distinct_exists: EQ
```

If `uname -m` prints `aarch64` while `file /sqlsolver/lib/libz3java.so` prints
`x86-64`, restart Colima with `--arch x86_64`.
