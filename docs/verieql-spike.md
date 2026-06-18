# VeriEQL Spike

VeriEQL ([VeriEQL/VeriEQL](https://github.com/VeriEQL/VeriEQL), OOPSLA 2024)
is a bounded SQL equivalence checker: it searches for a counterexample
database of up to `bound_size` rows per table satisfying declared integrity
constraints. A satisfiable result is a **sound refutation** with a concrete
witness database. An unsatisfiable result is only evidence up to the bound
and must never be reported as `PROVEN_EQUIVALENT`.

QuerySeal's intended role for VeriEQL is therefore a **refuter**, the mirror
of the prover backends: cross-check proven findings (an automated "no known
false PROVEN" gate), triage UNKNOWN results, and eventually give an LLM
candidate generator concrete corrective feedback.

## License

VeriEQL is licensed **CC BY-NC-SA 4.0** ([license.md](https://github.com/VeriEQL/VeriEQL/blob/main/license.md)),
verified upstream 2026-06-18. This is the one backend QuerySeal touches that is
**not** commercially usable, and the restriction is broader than "don't ship the
binary":

- **NonCommercial covers use, not just redistribution.** CC BY-NC-SA 4.0 defines
  NonCommercial as "not primarily intended for or directed toward commercial
  advantage or monetary compensation." Running VeriEQL inside a pipeline whose
  purpose is building or validating a commercial product is plausibly commercial
  use even if the binary is never distributed. "Internal use only" is not a
  reliable defense for an NC license.
- **ShareAlike is viral.** Any *adaptation* of VeriEQL (wrapping its encoder,
  modifying it, deriving code from it) must itself be released under
  CC BY-NC-SA 4.0, which would force a NonCommercial license onto whatever it is
  combined with.

Rules for this repo:

- VeriEQL stays entirely on the **research/evaluation** side: this spike,
  refutation experiments, and benchmarking QuerySeal's own provers against it.
- It must **not** appear in the commercial product or in any pipeline used to
  develop the commercial product. Integration drives a separate user-supplied
  checkout (`VERIEQL_DIR`); QuerySeal never bundles, vendors, or depends on it.
- VeriEQL is also the only **constraint-native** backend, so the commercial
  tiers must route FK/constraint-dependent verification through SQLSolver and
  QED instead — see below.
- To use VeriEQL commercially, obtain a separate commercial license from the
  authors (He, Zhao, Wang, Wang). This is a license-file reading, not legal
  advice; clear the NC-internal-use boundary with counsel before any launch.

For contrast, the prover backends are permissive and commercial-safe:
**SQLSolver** is Apache 2.0, and **QED** is MIT (prover) plus Apache 2.0
(parser) — all verified upstream 2026-06-18. Preserve their LICENSE/NOTICE
files anywhere they are redistributed.

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
  QuerySeal's post-fix premise vocabulary exactly: emit `primary` only for a
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

## Integration Status

Implemented: the `verieql` refuter backend
(`qseal/verifier/backends/verieql.py`) drives the checkout through
`scripts/verieql_driver.py` (JSON contract, subprocess into the checkout's
venv). Verdict mapping: counterexample -> `NOT_EQUIVALENT` with the witness
in the `counterexample` field; no counterexample up to the bound -> `UNKNOWN`
with a bounded-evidence reason, never `PROVEN_EQUIVALENT`; QUALIFY,
inexpressible premises (NULL-exempt unique keys), ambiguous unqualified
columns, and driver failures -> `UNSUPPORTED`. Schema attribute lists are
derived from the query pair via sqlglot scope resolution, following star
pass-through CTEs to base tables. The CLI entry point is `qseal refute`,
with `--fail-on refuted` for CI gates.

`qseal dbt crosscheck PROJECT --verieql-dir DIR` runs the refuter over
every proven scan finding and exits nonzero on any refutation. Fragment
findings are cross-checked at the fragment level: suggestions carry the
fragment pair (`fragment_original_sql` / `fragment_rewritten_sql`) rendered
from the **resolved** IR, in which pass-through CTE references are replaced
by their base tables. Rendering the raw body instead produced a false
refutation on the GitLab corpus (original said `FROM source`, rewritten said
`FROM bamboohr_headcount_intermediate`, and VeriEQL correctly treated those
as different relations) — a useful demonstration that the gate also catches
mistakes in the pair construction itself. Unqualified columns now resolve
through CTE projections during schema attribution, with abstention only when
multiple sources could define the column.

Both GitLab proven findings cross-check to bounded-OK at bound 2.

Remaining:

1. UNKNOWN triage in scan reports: refuted-with-witness versus bounded-OK.
2. Render full counterexample witness databases (the driver currently
   captures only the header; `generate_code` may be required).
