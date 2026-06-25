#!/usr/bin/env python3
"""Compare BIRD execution accuracy with QuerySeal formal prover verdicts.

For each pair: run gold and predicted SQL on the real SQLite database,
compare result sets (execution accuracy), then compare with our prover
verdict. The key metric is the overlap — especially cases where execution
accuracy says "correct" but our prover says "refuted" (execution false
positives) or vice versa.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import traceback
from pathlib import Path

DB_ROOT = Path("/tmp/bird_dev_data/dev_20240627/dev_databases")
PAIRS_FILE = Path("/tmp/bird_mini_pairs_clean.json")
VERDICT_FILE = Path("/tmp/bird_verdict_setops_full.json")
OUTPUT_FILE = Path("/tmp/bird_overlap_analysis.json")

# Execution accuracy timeout (seconds per query)
EXEC_TIMEOUT = 30


def run_query(db_path: Path, sql: str) -> tuple[bool, list, str]:
    """Run SQL on a SQLite database. Returns (success, results, error)."""
    try:
        conn = sqlite3.connect(str(db_path), timeout=EXEC_TIMEOUT)
        conn.execute("PRAGMA query_only = ON")
        cursor = conn.cursor()
        cursor.execute(sql)
        rows = cursor.fetchall()
        conn.close()
        return True, rows, ""
    except Exception as exc:
        return False, [], str(exc)


def normalize_results(rows: list) -> frozenset:
    """Normalize result rows for comparison (order-insensitive set comparison)."""
    # Convert each row to a tuple of stringified values for hashable comparison
    normalized = set()
    for row in rows:
        normalized.add(tuple(str(v) if v is not None else "NULL" for v in row))
    return frozenset(normalized)


def normalize_results_ordered(rows: list) -> tuple:
    """Normalize result rows preserving order (for ORDER BY queries)."""
    return tuple(tuple(str(v) if v is not None else "NULL" for v in row) for row in rows)


def main() -> None:
    pairs = json.loads(PAIRS_FILE.read_text())
    report = json.loads(VERDICT_FILE.read_text())

    # Build verdict lookup from pair_results (full per-pair verdicts)
    all_verdicts: dict[int, str] = {}
    for pr in report.get("pair_results", []):
        qid = pr.get("question_id")
        if qid is not None:
            all_verdicts[qid] = pr["label"]

    # Fall back to examples if pair_results not available
    if not all_verdicts:
        for bucket, examples in report.get("examples", {}).items():
            for ex in examples:
                qid = ex.get("question_id")
                if qid is not None:
                    all_verdicts[qid] = bucket

    results = []
    exec_correct = 0
    exec_wrong = 0
    exec_error = 0

    # Overlap matrix: [prover_verdict][exec_label]
    overlap: dict[str, dict[str, int]] = {}

    for pair in pairs:
        qid = pair["question_id"]
        db_id = pair["db_id"]
        gold_sql = pair["gold"].strip().rstrip(";")
        pred_sql = pair["predicted"].strip().rstrip(";")

        db_path = DB_ROOT / db_id / f"{db_id}.sqlite"
        if not db_path.exists():
            print(f"  SKIP qid={qid}: database not found at {db_path}")
            continue

        # Run gold
        gold_ok, gold_rows, gold_err = run_query(db_path, gold_sql)
        # Run predicted
        pred_ok, pred_rows, pred_err = run_query(db_path, pred_sql)

        if not gold_ok:
            exec_label = "gold_error"
            exec_error += 1
        elif not pred_ok:
            exec_label = "pred_error"
            exec_error += 1
        else:
            # Compare results — try both order-insensitive and ordered
            gold_set = normalize_results(gold_rows)
            pred_set = normalize_results(pred_rows)
            if gold_set == pred_set:
                exec_label = "exec_correct"
                exec_correct += 1
            else:
                exec_label = "exec_wrong"
                exec_wrong += 1

        prover_verdict = all_verdicts.get(qid, "not_in_verdict")

        # Track overlap
        if prover_verdict not in overlap:
            overlap[prover_verdict] = {}
        overlap[prover_verdict][exec_label] = overlap[prover_verdict].get(exec_label, 0) + 1

        # Flag interesting cases
        interesting = False
        if prover_verdict == "refuted" and exec_label == "exec_correct":
            interesting = True  # Execution false positive!
        if prover_verdict == "proven" and exec_label == "exec_wrong":
            interesting = True  # Execution false negative!

        results.append({
            "question_id": qid,
            "db_id": db_id,
            "difficulty": pair.get("difficulty", ""),
            "exec_label": exec_label,
            "prover_verdict": prover_verdict,
            "interesting": interesting,
            "gold_rows": len(gold_rows) if gold_ok else None,
            "pred_rows": len(pred_rows) if pred_ok else None,
            "gold_error": gold_err if not gold_ok else "",
            "pred_error": pred_err if not pred_ok else "",
            "gold_sql": gold_sql[:200],
            "pred_sql": pred_sql[:200],
        })

    # Print summary
    print(f"\n=== Execution Accuracy Summary ({len(results)} pairs) ===")
    print(f"  exec_correct: {exec_correct}")
    print(f"  exec_wrong:   {exec_wrong}")
    print(f"  exec_error:   {exec_error}")
    print(f"  exec_acc:     {exec_correct / (exec_correct + exec_wrong) * 100:.1f}%" if (exec_correct + exec_wrong) > 0 else "  exec_acc: N/A")

    print(f"\n=== Overlap Matrix (prover → exec) ===")
    print(f"{'prover':<22} {'exec_correct':>13} {'exec_wrong':>11} {'gold_error':>11} {'pred_error':>11}")
    print("-" * 70)
    for prover in sorted(overlap.keys()):
        row = overlap[prover]
        print(f"{prover:<22} {row.get('exec_correct', 0):>13} {row.get('exec_wrong', 0):>11} {row.get('gold_error', 0):>11} {row.get('pred_error', 0):>11}")

    # The key numbers
    refuted_but_correct = overlap.get("refuted", {}).get("exec_correct", 0)
    proven_but_wrong = overlap.get("proven", {}).get("exec_wrong", 0)
    bounded_but_wrong = overlap.get("bounded_unknown", {}).get("exec_wrong", 0)
    bounded_but_correct = overlap.get("bounded_unknown", {}).get("exec_correct", 0)

    print(f"\n=== Key Findings ===")
    print(f"  PROVER REFUTED but EXEC CORRECT (exec false positives):  {refuted_but_correct}")
    print(f"  PROVER PROVEN  but EXEC WRONG   (exec false negatives): {proven_but_wrong}")
    print(f"  BOUNDED UNKNOWN but EXEC WRONG:                          {bounded_but_wrong}")
    print(f"  BOUNDED UNKNOWN but EXEC CORRECT:                        {bounded_but_correct}")

    # Show interesting cases
    interesting_cases = [r for r in results if r["interesting"]]
    if interesting_cases:
        print(f"\n=== Interesting Cases ({len(interesting_cases)}) ===")
        for case in interesting_cases:
            print(f"\n  qid={case['question_id']} db={case['db_id']} difficulty={case['difficulty']}")
            print(f"  prover: {case['prover_verdict']}  exec: {case['exec_label']}")
            print(f"  gold:   {case['gold_sql'][:120]}")
            print(f"  pred:   {case['pred_sql'][:120]}")
            if case["gold_error"]:
                print(f"  gold_error: {case['gold_error'][:100]}")
            if case["pred_error"]:
                print(f"  pred_error: {case['pred_error'][:100]}")
            print(f"  gold_rows={case['gold_rows']}  pred_rows={case['pred_rows']}")

    # Write full output
    output = {
        "n_pairs": len(results),
        "exec_correct": exec_correct,
        "exec_wrong": exec_wrong,
        "exec_error": exec_error,
        "overlap": overlap,
        "refuted_but_exec_correct": refuted_but_correct,
        "proven_but_exec_wrong": proven_but_wrong,
        "bounded_but_exec_wrong": bounded_but_wrong,
        "bounded_but_exec_correct": bounded_but_correct,
        "results": results,
    }
    OUTPUT_FILE.write_text(json.dumps(output, indent=2))
    print(f"\nWrote {OUTPUT_FILE}")


if __name__ == "__main__":
    main()