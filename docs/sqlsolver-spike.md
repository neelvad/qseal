# SQLSolver Spike

SQLSolver ships Linux native Z3 libraries, so run it in Ubuntu rather than
macOS directly.

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
apt-get install -y openjdk-17-jdk ca-certificates
./gradlew fatjar

/snowprove/scripts/run_sqlsolver_fixture.sh
CASE_NAME=all /snowprove/scripts/run_sqlsolver_fixture.sh
CASE_NAME=unsafe_distinct /snowprove/scripts/run_sqlsolver_fixture.sh
CASE_NAME=unused_left_join /snowprove/scripts/run_sqlsolver_fixture.sh
```

The helper flattens each fixture query to one line because SQLSolver's CLI
treats corresponding lines in `-sql1` and `-sql2` as query pairs.

Observed successful fixture results:

```text
redundant_distinct: EQ
unsafe_distinct: NEQ
unused_left_join: EQ
join_distinct_exists: EQ
```

If `uname -m` prints `aarch64` while `file /sqlsolver/lib/libz3java.so` prints
`x86-64`, restart Colima with `--arch x86_64`.
