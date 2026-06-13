# LLM Candidate Generation and Verification

The untrusted-generator / trusted-verifier loop from `AGENTS.md`, as shipped.
The generator proposes; only `PROVEN_EQUIVALENT` survives.

## Generate

```bash
export ANTHROPIC_API_KEY=...
uv run python scripts/generate_llm_candidates.py PROJECT --out BUNDLES_DIR --limit 5
uv run python scripts/generate_llm_candidates.py PROJECT --out BUNDLES_DIR --use-batches
uv run python scripts/generate_llm_candidates.py PROJECT --out BUNDLES_DIR --dry-run
```

Targets are models that survive Jinja preprocessing, parse (whole-query or at
least one fragment), and reference at least one constrained table. Prompts are
premise-targeted: trusted dbt-test constraints are rendered in NULL-faithful
vocabulary ("unique among non-NULL values", "never NULL") with the five rule
patterns as worked examples, and the model is told an empty candidate list is
a good answer. Direct mode prompt-caches the shared system prompt;
`--use-batches` runs through the Batches API at half price for full-corpus
runs.

Each bundle conforms to the `candidates check` metadata contract and records
generator provenance: model id, prompt hash, timestamp, token usage.

## Verify

Verification is two-phase because SQLSolver needs the x86 Linux container
while VeriEQL runs natively on macOS:

```bash
# Phase A (macOS): parse -> identity -> builtin -> VeriEQL refute/cross-check
uv run python scripts/verify_llm_candidates.py BUNDLES_DIR \
  --project PROJECT --verieql-dir ~/workspace/snowprove-eval/VeriEQL \
  --report-file report-a.json

# Phase B (container): parse -> identity -> builtin -> SQLSolver
scripts/run_llm_verification_sqlsolver.sh BUNDLES_DIR PROJECT report-b.json

# Merge: best verdict per candidate; proven-vs-refuted conflicts alarm
uv run python scripts/verify_llm_candidates.py \
  --merge-reports report-a.json report-b.json --report-file final.json
```

## Buckets

| Bucket | Meaning |
|---|---|
| `proven` | A sound prover (builtin rule replay or SQLSolver) proved equivalence under the trusted premises. The only acceptable findings. |
| `refuted` | SQLSolver returned NEQ or VeriEQL produced a counterexample database. |
| `bounded_ok` | VeriEQL found no counterexample up to the bound. Evidence, not proof. |
| `unknown` | Every verifier abstained. |
| `identity` | Candidate is the original modulo formatting; discarded. |
| `invalid` | Candidate SQL does not parse. |
| `conflict` | One verifier proved what another refuted — a soundness alarm; the merge exits nonzero. |

The four agreed metrics map onto these: candidate parse rate (1 - invalid),
proven rate (headline), refuted rate (worth of a counterexample-guided repair
loop), bounded-OK rate (the prover-coverage gap that decides whether QED is
worth integrating).

## First Full-Corpus Run (GitLab analytics, 2026-06-12)

Batch `msgbatch_018u82DNmrNdhsr5BqCQbBpv`: 341 target models, 400 candidates,
zero generation errors, ~$4.90 via the Batches API with prompt caching.

Merged verification results (phase A: builtin + VeriEQL on macOS; phase B:
builtin + SQLSolver in the container, 60s timeout):

| Bucket | Count | Rate |
|---|---|---|
| proven | 233 | 58% |
| bounded_ok | 34 | 9% |
| unknown | 122 | 31% |
| identity | 11 | 3% |
| refuted / invalid / conflict | 0 | 0% |

- The 233 proven rewrites span **216 distinct models** — 63% of targeted
  models received at least one formally proven rewrite. The rule-based
  scanner found 2 on the same corpus.
- **227 of the 233 proven candidates were independently bounded-OK by
  VeriEQL** — two unrelated verification systems (LIA*/SMT proving and
  bounded model checking) agree, with zero proven-vs-refuted conflicts.
- Zero candidates were refuted and zero failed to parse: premise-targeted
  prompting with an explicit empty-list option produced no detectably wrong
  SQL in 400 attempts.
- The unknown bucket is almost entirely genuine solver incompleteness: 154
  of 156 phase-B unknowns are SQLSolver parsing the pair and returning
  UNKNOWN (zero timeouts after schema filtering; one Calcite parse error;
  one name-collision abstention). This is the measured signal for the next
  levers: fragment-diff verification (send the solver only the changed CTE)
  and a QED prover added to the cascade.
- The candidate-sizing instruction mattered: the pre-tweak smoke run's
  whole-query restructurings were unverifiable; the post-tweak mix of
  minimal fragment-scoped candidates drove both the proven rate and
  VeriEQL's 65% bounded-OK coverage.

Proven findings remain advisory until reviewed: equivalence is proven under
trusted dbt-test premises, and no performance claim is made.

### With QED in the cascade (same corpus, 2026-06-12)

Adding the native QED prover (`--qed`, see `docs/qed-spike.md`) as a third
phase and merging all three reports:

| Bucket | Count | Rate |
|---|---|---|
| proven (233 sqlsolver + 38 qed) | **271** | **67.8%** |
| bounded_ok | 3 | 0.8% |
| unknown | 115 | 28.7% |
| identity | 11 | 2.8% |
| refuted / invalid / conflict | 0 | 0% |

**243 distinct models** (71% of targeted) now carry at least one formally
proven rewrite. The QED pass ran natively in minutes; standalone it proved
264/400 — heavily overlapping SQLSolver's 233 but with complementary wins on
CTE/projection shapes, while SQLSolver retains exclusive coverage of the
join-shaped rewrites.

### With coverage levers (same corpus, 2026-06-12)

Three additions: provers run QED-first; fragment-diff pair reduction (when
the pair differs in exactly one CTE body, provers see only that fragment —
sound for proving by congruence, never used for refutation verdicts);
and QED frontend prep (unknown functions declared as uninterpreted scalars —
sound because equivalence under arbitrary function semantics implies
equivalence under the real ones — plus varchar typing for columns compared
against string literals).

Merged result (after the Modal run below): **282/400 proven (70.5%)**,
zero refuted, zero conflicts. The upgraded local-only pass proves 266 by
itself — within 15 of the full multi-prover union, making routine
verification a native, minutes-long operation. Residual unknowns: 74
Calcite parse rejects (deeper dialect normalization), 43 ambiguous-column
abstentions (schema attribution), 6 genuine NotProvable.

## Modal Runner

`scripts/modal_verify.py` runs the identical verification script on Modal,
sharded across containers, with the QED toolchain and SQLSolver jar baked
into a pinned-commit image (everything native x86 - SQLSolver needs no
emulation there). Local runs remain first-class; the cloud path exists for
iteration speed and larger corpora.

```bash
uv run modal run scripts/modal_verify.py \
  --bundles-dir snowprove-runs/llm-candidates/gitlab-full \
  --report-file snowprove-runs/llm-candidates/modal-full-report.json --shards 40
```

First full-corpus benchmark: **400 candidates, full cascade, 69 seconds
wall-clock** across 40 containers (~$0.30 of compute; the one-time image
build takes ~15 minutes and is cached). The single Modal pass proved 276 -
within six of the four-pass accumulated local total - with zero conflicts
against any local verdict.

## Second Corpus: Mattermost (breadth check, 2026-06-13)

Ran the full pipeline unmodified on `mattermost/mattermost-data-warehouse`
(`transform/mattermost-analytics`, 254 models, Snowflake, 287 unique +
206 not_null tests) to test generalization beyond GitLab.

What generalized cleanly:

- **The pipeline runs unchanged** on a second company's Snowflake dbt
  project: scan, generate (Batches), three-prover verify, DuckDB Tier-1,
  Snowflake Tier-2 EXPLAIN, all without code changes.
- **Soundness generalizes hard: 0 refuted across both corpora (0 / 406
  candidates).** Premise-targeted generation produced no detectably wrong
  SQL on either codebase.
- The two proven Mattermost rewrites reproduced both ends of the
  benefit axis at once: `fct_events_daily_snapshot` is proven AND drops a
  Snowflake aggregate AND runs 1.23x on DuckDB; `int_legacy_licenses_deduped`
  is proven but adds work on Snowflake (the suppress case).

What did *not* transfer, and why it matters:

- **Target yield is dbt-project-style-dependent.** Only 10 of 254 models
  (4%) are parseable-and-premise-bearing, versus GitLab's ~341 of 2206
  (15%). GitLab's simple `*_xf` transform models read directly from tested
  tables; Mattermost's simple models are thin staging over *untested* raw
  sources, while its premise-bearing tables feed join-heavy marts that do
  not parse. Of 90 parseable models, only 3 reference a constrained table.
- **Proven rate among candidates dropped (2/6 vs GitLab 0.70)** but the
  gap is fully explained by known limitations, not method failure: 3 of 4
  unknowns are the schema-attribution gap (ambiguous columns across
  multi-source scopes), 1 is QUALIFY. Zero were refuted or unprovable for
  novel reasons.

Conclusion: operational and soundness generalization are confirmed; the
binding constraint on breadth is parser/attribution coverage of
join-and-aggregate-heavy models, not corpus availability. A second corpus
helps only where its *simple* models read from *tested* tables - which is a
property of project style, not project size. This reprioritizes manifest
ingestion and join/aggregate parser coverage over corpus hunting.
