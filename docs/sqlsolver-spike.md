# SQLSolver Spike

SQLSolver links Z3 through JNI. On Apple Silicon you build arm64 macOS
Z3 Java bindings once and run SQLSolver natively, with no container and
no emulation overhead.

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

## Fixture scripts

The SQLSolver fixture helpers (`scripts/run_sqlsolver_fixture.sh`,
`scripts/run_qseal_sqlsolver_fixture.sh`,
`scripts/run_qseal_sqlsolver_candidate_smoke.sh`,
`scripts/run_qseal_sqlsolver_pair.sh`) run inside any Linux environment
with SQLSolver's bundled x86 Z3 libraries — for example the Modal remote
runner (`scripts/modal_verify.py`). They default to
`scripts/sqlsolver_command.sh`, the Linux wrapper that sets
`LD_LIBRARY_PATH`; override `SOLVER_COMMAND` to use
`scripts/run_sqlsolver_native.sh` on arm64 macOS.

Observed successful fixture results:

```text
redundant_distinct: EQ
unsafe_distinct: NEQ
unused_left_join: EQ
fk_inner_join: EQ
join_distinct_exists: EQ
```

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
