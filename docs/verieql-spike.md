# VeriEQL Spike

VeriEQL ([VeriEQL/VeriEQL](https://github.com/VeriEQL/VeriEQL), OOPSLA 2024)
is a bounded SQL equivalence checker: it searches for a counterexample
database of up to `bound_size` rows per table satisfying declared integrity
constraints. A satisfiable result is a **sound refutation** with a concrete
witness database. An unsatisfiable result is only evidence up to the bound
and must never be reported as `PROVEN_EQUIVALENT`.

Snowprove's intended role for VeriEQL is therefore a **refuter**, the mirror
of the prover backends: cross-check proven findings (an automated "no known
false PROVEN" gate), triage UNKNOWN results, and eventually give an LLM
candidate generator concrete corrective feedback.

## License

VeriEQL is licensed **CC BY-NC-SA 4.0 (NonCommercial)**. Snowprove must not
bundle, vendor, or depend on it. Integration drives a separate user-supplied
checkout, mirroring the SQLSolver arrangement. Revisit before any commercial
use of the combined workflow.

## Running the Spike

```bash
scripts/run_verieql_spike.sh
VERIEQL_DIR=/path/to/VeriEQL scripts/run_verieql_spike.sh
```

The wrapper creates `.venv` inside the VeriEQL checkout with Python 3.11,
pinned `z3-solver==4.12.2.0` and `setuptools<81` (newer versions break
imports), and copies VeriEQL's patched `z3py_libs/*.py` over the installed
z3 modules, which their code requires (their wrappers pass `ctx=` keywords
that stock z3py rejects).

## Spike Results (2026-06-10)

Sound rewrites with correctly encoded premises verify at bound 2:

- DISTINCT removal with `primary` on the projected key
- redundant `IS NOT NULL` removal with `not_null`
- unused LEFT JOIN elimination with `primary` on the joined key

All four of the pre-fix soundness bugs found by hand this week are
**refuted with concrete counterexamples**: DISTINCT removal without
constraints, not-null filter removal without the premise, LEFT JOIN
elimination on a non-unique key, and the COALESCE projection variant. The
automated cross-check gate would have caught every one of them.

Invalid SQL (the dangling-reference output the CTE-guard bug used to
produce) fails loudly with `UnknownColumnError` rather than silently.

## Constraint Encoding

The attribute reference syntax is `TABLE__COLUMN` inside `{"value": ...}`:

- `{"primary": [{"value": "T__C"}]}` encodes **strict uniqueness plus NOT
  NULL** (pairwise distinct values and `Not(NULL)` per row). This matches
  snowprove's post-fix premise vocabulary exactly: emit `primary` only for a
  trusted unique key whose columns are also trusted non-null.
- `{"not_null": {"value": "T__C"}}` encodes NOT NULL. The operand must be a
  single attribute dict; a list of dicts crashes their encoder.
- A NULL-exempt unique constraint (dbt-test semantics on a nullable column)
  is not expressible. Omitting a trusted premise can produce **false
  refutations**, so the refuter must abstain when the catalog carries
  premises it cannot encode faithfully.

## Limits Found

- **QUALIFY is silently ignored**: a QUALIFY-filtered query is reported
  bounded-equivalent to its unfiltered form. The refuter must refuse any
  pair containing QUALIFY.
- `EXISTS` predicates are unsupported (`NotSupportedError`), so
  `rewrite_join_distinct_to_exists` findings cannot be cross-checked.
- Qualified relation names (`db.schema.table`) are unknown databases; reuse
  the relation unqualification from the SQLSolver backend.
- Dialect is MySQL-flavored (`mo-sql-parsing`); Snowflake-specific functions
  will be unsupported and must map to abstention.

## Integration Plan

1. A `verieql` refuter backend (subprocess into the checkout's venv, JSON
   contract) that maps: counterexample found -> `NOT_EQUIVALENT` with the
   witness in the existing `counterexample` field; unsat at bound k -> an
   annotation on `UNKNOWN`, never `PROVEN_EQUIVALENT`; unsupported SQL or
   inexpressible premises -> abstain.
2. A cross-check harness that runs the refuter over every
   `PROVEN_EQUIVALENT` finding from scans and the corpus, failing CI on any
   counterexample.
3. UNKNOWN triage in scan reports: refuted-with-witness versus bounded-OK.
