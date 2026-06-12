# QED Spike

QED ([qed-solver](https://github.com/qed-solver), VLDB 2024) is a SQL
equivalence decider built on Q-expressions with a decidable fragment. The
spike evaluated it as a second prover in the cascade alongside SQLSolver.

## Toolchain

Two components, both run natively on Apple Silicon — no container:

- **Prover** (`qed-solver/prover`): Rust, built with a nightly toolchain
  (`cargo +nightly build --release`, needs `libclang` and z3 headers —
  `CPATH=/opt/homebrew/include LIBRARY_PATH=/opt/homebrew/lib`). Requires
  `z3` and `cvc5` executables on PATH at runtime (z3 via Homebrew; cvc5 from
  its GitHub release binaries — there is no Homebrew formula).
- **Parser** (`qed-solver/parser`): Java/Calcite, Maven. Upstream pins Java
  19 *preview*; those features are final in 21, so patch `pom.xml` to
  source/target 21 and drop `--enable-preview` to build on a modern JDK.

Input: one `.sql` file per pair with MySQL-valid `CREATE TABLE` statements
plus exactly two SELECTs. The parser emits `.json` for the prover; verdicts
are `Provable` / `NotProvable` per file (the stats carry a
`complete_fragment` flag — a future trustworthy-NEQ channel).

## Premise semantics — same trap as SQLSolver

Spike case: DISTINCT removal justified by `UNIQUE` on a *nullable* column
is **Provable** by QED. That is unsound under SQL/dbt unique-test semantics
(duplicate NULLs survive), so QED interprets `UNIQUE` as strict uniqueness,
NULLs included. The premise discipline is therefore identical to the other
backends: **emit uniqueness only when the key columns are also trusted
non-null** (`scripts/qed_spike_unknowns.py` implements this).

## Coverage: complementary, not dominant

On snowprove's rule shapes, QED is *weaker* than SQLSolver: unused LEFT
JOIN elimination (with or without non-null unique keys) and JOIN+DISTINCT
to EXISTS are NotProvable, while SQLSolver proves both. DISTINCT removal
and redundant IS NOT NULL removal prove fine.

On the 154 genuine SQLSolver UNKNOWNs from the first full LLM-candidate run
(`docs/llm-candidates.md`):

| Stage | Count |
|---|---|
| SQLSolver-UNKNOWN candidates | 154 |
| Converted to QED inputs (schema extraction succeeded) | 93 |
| Parsed by Calcite | 33 |
| **Proven by QED** | **33 — 100% of parsed** |

31 of the 33 were independently bounded-OK by VeriEQL; zero refuted. Adding
QED to the cascade lifts the full-run proven rate from 233/400 (58%) to
**266/400 (66.5%)** with seconds of prover time.

The funnel also reprioritizes earlier ideas with data:

- 61/154 lost at schema extraction (ambiguous unqualified columns across
  CTE scopes) — improving attribution helps every backend.
- 60/93 lost at Calcite parsing (Snowflake-isms, strict type checking with
  all-INTEGER schemas) — **dialect normalization and literal-driven column
  typing are now justified for QED**, where for SQLSolver they barely
  mattered (1 parse error in 400).

## Conclusion

Integrate QED as a third prover backend (cascade: builtin -> SQLSolver ->
QED; any sound prover's EQ suffices). Operationally it is the cheapest
backend snowprove has: native arm binaries, no container, millisecond-to-
second verdicts. License: prover is MIT, parser is Apache 2.0 — both compatible with bundling or CI use, unlike VeriEQL's NonCommercial license.
