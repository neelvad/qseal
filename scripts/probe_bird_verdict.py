"""BIRD mini-dev verdict funnel (builtin + optional formal-prover cascade).

Reads aligned (gold, predicted) pairs built from the official BIRD mini-dev
gold file and a predictions file keyed by question_id, then runs the qseal
verification cascade on every pair where both sides parse under the
supported subset.

Cascade order, cheapest first, and the first decisive tier wins:

1. builtin verifier -- normalized IR identity or one of the five supported
   rewrite-rule replays. Always runs (no external toolchain).
2. QED (native Calcite parser + Rust prover) -- optional, enabled with --qed
   and configured via QSEAL_QED_PARSER_JAR / QSEAL_QED_PROVER / QSEAL_QED_JAVA.
3. SQLSolver (native arm64 macOS or x86 container / Modal) -- optional,
   enabled with --sqlsolver-command CMD. On Apple Silicon use
   scripts/run_sqlsolver_native.sh after scripts/build_z3_java_native.sh.
4. VeriEQL refuter (external checkout, CC BY-NC-SA -- never bundled) --
   optional, enabled with --verieql-dir DIR. A counterexample is a sound
   refutation; the absence of one up to the bound is bounded evidence and
   never promotes a pair to PROVEN_EQUIVALENT.

With no formal-tier flags the script reports the locally-runnable builtin
baseline only (the headline proven rate needs the formal-prover environment).

Usage:
    python scripts/probe_bird_verdict.py \
        --pairs /tmp/bird_mini_pairs.json \
        --dialect sqlite \
        --report-file /tmp/bird_verdict_report.json

    python scripts/probe_bird_verdict.py \
        --pairs /tmp/bird_mini_pairs.json --qed \
        --sqlsolver-command 'java -jar /path/sqlsolver.jar' \
        --verieql-dir /path/VeriEQL --verieql-bound 2
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from qseal.constraints.model import ConstraintCatalog
from qseal.dialects import SUPPORTED_DIALECTS
from qseal.parser.sqlglot_parser import UnsupportedSqlError, parse_select
from qseal.rewrites.base import VerificationStatus
from qseal.verifier.backends.builtin import BuiltinVerifierBackend
from qseal.verifier.backends.qed import QedBackend
from qseal.verifier.backends.sqlsolver import SqlSolverBackend
from qseal.verifier.backends.verieql import VeriEqlBackend
from qseal.verifier.model import VerificationResult


def _load_pairs(path: str) -> list[dict]:
    data = json.loads(Path(path).read_text())
    if isinstance(data, dict):
        data = list(data.values())
    return data


def _add(store: dict[str, list[dict]], key: str, item: dict, limit: int = 5) -> None:
    store.setdefault(key, [])
    if len(store[key]) < limit:
        store[key].append(item)


def _decisive(status: VerificationStatus) -> bool:
    return status in (VerificationStatus.PROVEN_EQUIVALENT, VerificationStatus.NOT_EQUIVALENT)


class Cascade:
    """Ordered verification tiers; first decisive result wins."""

    def __init__(self, dialect: str, *, qed: bool, sqlsolver_command: str | None,
                 verieql_dir: str | None, verieql_bound: int, timeout: int | None) -> None:
        self.dialect = dialect
        self.builtin = BuiltinVerifierBackend()
        self.qed = QedBackend(timeout_seconds=timeout) if qed else None
        self.sqlsolver = (
            SqlSolverBackend(solver_command=sqlsolver_command, timeout_seconds=timeout)
            if sqlsolver_command else None
        )
        self.verieql = (
            VeriEqlBackend(verieql_dir=verieql_dir, bound=verieql_bound, timeout_seconds=timeout)
            if verieql_dir else None
        )

    @property
    def tiers(self) -> list[str]:
        active = ["builtin"]
        if self.qed is not None:
            active.append("qed")
        if self.sqlsolver is not None:
            active.append("sqlsolver")
        if self.verieql is not None:
            active.append("verieql")
        return active

    def run(
        self, gold: str, pred: str, constraints: ConstraintCatalog
    ) -> tuple[VerificationResult, str]:
        """Return (result, tier_name). The builtin tier always runs first.

        Formal-prover abstentions (UNSUPPORTED because a tier is unconfigured
        or cannot structurally handle a pair) never downgrade the builtin
        verdict: a builtin UNKNOWN stays UNKNOWN rather than becoming a
        misleading "unsupported". Only a decisive result or a genuine UNKNOWN
        (a prover that actually ran and could not decide) overrides builtin.
        """
        best = self.builtin.verify(gold, pred, constraints, dialect=self.dialect)
        best_tier = "builtin"
        if _decisive(best.status):
            return best, best_tier

        for tier_name, backend in self._formal_provers():
            result = backend.verify(gold, pred, constraints, dialect=self.dialect)
            if _decisive(result.status):
                return result, tier_name
            # A genuine UNKNOWN (prover ran, could not decide) is more
            # informative than the builtin rule-replay UNKNOWN; adopt it.
            if result.status == VerificationStatus.UNKNOWN:
                best, best_tier = result, tier_name

        # The refuter never proves, but it can refute (NOT_EQUIVALENT) or yield
        # bounded evidence (UNKNOWN with a "bounded" reason). Run it last so a
        # counterexample becomes the verdict only when no prover claimed
        # equivalence first.
        if self.verieql is not None:
            result = self.verieql.refute(gold, pred, constraints, dialect=self.dialect)
            if result.status == VerificationStatus.NOT_EQUIVALENT:
                return result, "verieql"
            # VeriEQL only returns UNKNOWN for the bounded-OK case (no
            # counterexample up to the bound), which is sound evidence, not a
            # proof of equivalence. Tag it so the report can distinguish
            # bounded_unknown from a plain prover UNKNOWN.
            if result.status == VerificationStatus.UNKNOWN:
                return result, "verieql_bounded"

        return best, best_tier

    def _formal_provers(self):
        if self.qed is not None:
            yield "qed", self.qed
        if self.sqlsolver is not None:
            yield "sqlsolver", self.sqlsolver


def _probe(pairs: list[dict], cascade: Cascade) -> dict:
    constraints = ConstraintCatalog()
    buckets: Counter[str] = Counter()
    tier_counts: Counter[str] = Counter()
    examples: dict[str, list[dict]] = {}
    exact_text_match = 0

    for pair in pairs:
        gold = pair["gold"]
        pred = pair["predicted"]
        if gold.strip() == pred.strip():
            exact_text_match += 1

        try:
            parse_select(gold, dialect=cascade.dialect)
        except UnsupportedSqlError:
            _add(examples, "gold_parse_fail", pair)
            buckets["gold_parse_fail"] += 1
            continue
        try:
            parse_select(pred, dialect=cascade.dialect)
        except UnsupportedSqlError:
            _add(examples, "pred_parse_fail", pair)
            buckets["pred_parse_fail"] += 1
            continue

        result, tier = cascade.run(gold, pred, constraints)
        label = _status_label(result.status)
        # Distinguish VeriEQL bounded evidence from a plain prover UNKNOWN.
        if label == "unknown" and tier == "verieql_bounded":
            label = "bounded_unknown"
        buckets[label] += 1
        tier_counts[tier] += 1
        if label != "unknown" or len(examples.get("unknown", [])) < 3:
            _add(
                examples,
                label,
                {
                    **pair,
                    "rule_name": result.rule_name,
                    "method": result.verification_method,
                    "tier": tier,
                    "reason": result.reason,
                    "counterexample": result.counterexample,
                },
            )

    return {
        "n_pairs": len(pairs),
        "tiers": cascade.tiers,
        "exact_text_match": exact_text_match,
        "buckets": dict(buckets),
        "tier_final_counts": dict(tier_counts),
        "examples": {k: v[:5] for k, v in examples.items()},
    }


def _status_label(status: VerificationStatus) -> str:
    return {
        VerificationStatus.PROVEN_EQUIVALENT: "proven",
        VerificationStatus.NOT_EQUIVALENT: "refuted",
        VerificationStatus.UNSUPPORTED: "unsupported",
        VerificationStatus.UNKNOWN: "unknown",
    }.get(status, "unknown")


def _print(report: dict) -> None:
    n = report["n_pairs"]
    tiers = report["tiers"]
    label = "builtin tier only" if tiers == ["builtin"] else "cascade: " + " -> ".join(tiers)
    print(f"\nBIRD mini-dev verdict funnel (n={n}, {label})")
    print(f"exact text match (gold==predicted): {report['exact_text_match']}")
    print()
    for key in (
        "proven", "refuted", "bounded_unknown", "unknown", "unsupported",
        "pred_parse_fail", "gold_parse_fail",
    ):
        count = report["buckets"].get(key, 0)
        pct = 100.0 * count / n if n else 0.0
        print(f"  {key:<18}: {count:>5}  ({pct:5.1f}%)")
    if report["tier_final_counts"]:
        print("\nfinal verdict tier counts (per pair):")
        for tier, count in sorted(report["tier_final_counts"].items()):
            print(f"  {tier:<18}: {count:>5}")
    print()
    for key in ("proven", "refuted"):
        exs = report["examples"].get(key, [])
        if exs:
            print(f"-- {key} examples --")
            for e in exs:
                print(
                    f"  qid={e['question_id']} db={e['db_id']} "
                    f"tier={e.get('tier')} method={e.get('method')}"
                )
                print(f"    gold: {e['gold'][:120]}")
                print(f"    pred: {e['predicted'][:120]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pairs", required=True,
        help="JSON list of {question_id, db_id, gold, predicted}",
    )
    parser.add_argument("--dialect", default="sqlite")
    parser.add_argument("--report-file", default=None)
    parser.add_argument("--qed", action="store_true", help="Enable the QED prover tier.")
    parser.add_argument(
        "--sqlsolver-command", default=None,
        help="SQLSolver invocation command (enables the SQLSolver tier).",
    )
    parser.add_argument(
        "--verieql-dir", default=None,
        help="Path to an external VeriEQL checkout (enables the refuter tier).",
    )
    parser.add_argument("--verieql-bound", type=int, default=2, help="VeriEQL bound (default 2).")
    parser.add_argument(
        "--timeout", type=int, default=None,
        help="Per-tier timeout in seconds for QED/SQLSolver/VeriEQL.",
    )
    args = parser.parse_args()

    if args.dialect not in SUPPORTED_DIALECTS:
        parser.error(f"unsupported dialect: {args.dialect}")
    cascade = Cascade(
        args.dialect,
        qed=args.qed,
        sqlsolver_command=args.sqlsolver_command,
        verieql_dir=args.verieql_dir,
        verieql_bound=args.verieql_bound,
        timeout=args.timeout,
    )
    pairs = _load_pairs(args.pairs)
    report = _probe(pairs, cascade)
    _print(report)
    if args.report_file:
        Path(args.report_file).write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(f"\nwrote {args.report_file}")


if __name__ == "__main__":
    main()
