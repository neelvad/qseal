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
