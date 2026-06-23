"""BIRD mini-dev verdict funnel (builtin tier).

Reads aligned (gold, predicted) pairs built from the official BIRD mini-dev
gold file and a predictions file keyed by question_id, then runs the qseal
builtin verifier on every pair where both sides parse under the supported
subset. The builtin tier proves equivalence only by normalized IR identity or
by replaying one of the five supported rewrite rules; arbitrary (gold,
predicted) pairs therefore mostly return UNKNOWN. The formal provers (QED,
SQLSolver) and the VeriEQL refuter are intentionally not invoked here -- they
need external toolchains -- so this script reports the locally-runnable
baseline only.

Usage:
    python scripts/probe_bird_verdict.py \
        --pairs /tmp/bird_mini_pairs.json \
        --dialect sqlite \
        --report-file /tmp/bird_verdict_report.json
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


def _load_pairs(path: str) -> list[dict]:
    data = json.loads(Path(path).read_text())
    if isinstance(data, dict):
        data = list(data.values())
    return data


def _probe(pairs: list[dict], dialect: str) -> dict:
    backend = BuiltinVerifierBackend()
    constraints = ConstraintCatalog()
    buckets: Counter[str] = Counter()
    examples: dict[str, list[dict]] = {}
    exact_text_match = 0

    for pair in pairs:
        gold = pair["gold"]
        pred = pair["predicted"]
        if gold.strip() == pred.strip():
            exact_text_match += 1

        try:
            parse_select(gold, dialect=dialect)
        except UnsupportedSqlError:
            _add(examples, "gold_parse_fail", pair)
            buckets["gold_parse_fail"] += 1
            continue
        try:
            parse_select(pred, dialect=dialect)
        except UnsupportedSqlError:
            _add(examples, "pred_parse_fail", pair)
            buckets["pred_parse_fail"] += 1
            continue

        result = backend.verify(gold, pred, constraints, dialect=dialect)
        label = _status_label(result.status)
        buckets[label] += 1
        if label != "unknown" or len(examples.get("unknown", [])) < 3:
            _add(examples, label, {**pair, "rule_name": result.rule_name, "reason": result.reason})

    return {
        "n_pairs": len(pairs),
        "exact_text_match": exact_text_match,
        "buckets": dict(buckets),
        "examples": {k: v[:5] for k, v in examples.items()},
    }


def _status_label(status: VerificationStatus) -> str:
    return {
        VerificationStatus.PROVEN_EQUIVALENT: "proven",
        VerificationStatus.NOT_EQUIVALENT: "refuted",
        VerificationStatus.UNSUPPORTED: "unsupported",
        VerificationStatus.UNKNOWN: "unknown",
    }.get(status, "unknown")


def _add(store: dict[str, list[dict]], key: str, item: dict) -> None:
    store.setdefault(key, [])
    if len(store[key]) < 5:
        store[key].append(item)


def _print(report: dict) -> None:
    n = report["n_pairs"]
    print(f"\nBIRD mini-dev verdict funnel (n={n}, builtin tier only)")
    print(f"exact text match (gold==predicted): {report['exact_text_match']}")
    print()
    for key in (
        "proven", "refuted", "unknown", "unsupported",
        "pred_parse_fail", "gold_parse_fail",
    ):
        count = report["buckets"].get(key, 0)
        pct = 100.0 * count / n if n else 0.0
        print(f"  {key:<18}: {count:>5}  ({pct:5.1f}%)")
    print()
    for key in ("proven", "refuted"):
        exs = report["examples"].get(key, [])
        if exs:
            print(f"-- {key} examples --")
            for e in exs:
                print(f"  qid={e['question_id']} db={e['db_id']} rule={e.get('rule_name')}")
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
    args = parser.parse_args()

    if args.dialect not in SUPPORTED_DIALECTS:
        parser.error(f"unsupported dialect: {args.dialect}")
    dialect = args.dialect
    pairs = _load_pairs(args.pairs)
    report = _probe(pairs, dialect)
    _print(report)
    if args.report_file:
        Path(args.report_file).write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(f"\nwrote {args.report_file}")


if __name__ == "__main__":
    main()