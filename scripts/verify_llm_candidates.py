# Verify LLM candidate bundles produced by scripts/generate_llm_candidates.py.
#
# Cascade, cheapest first: parse -> identity filter -> builtin prover ->
# VeriEQL refutation of non-proven survivors and cross-check of proven ones.
# Acceptance is PROVEN_EQUIVALENT only; bounded-OK is evidence, never a proof.
#
#   uv run python scripts/verify_llm_candidates.py BUNDLES_DIR --project PROJECT \
#       [--verieql-dir ~/workspace/snowprove-eval/VeriEQL] [--dialect snowflake]
#       [--solver-command CMD]   # SQLSolver, typically inside the x86 container
#   uv run python scripts/verify_llm_candidates.py --merge-reports A.json B.json \
#       --report-file final.json
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import sqlglot
from sqlglot.errors import SqlglotError

from snowprove.constraints.model import ConstraintCatalog
from snowprove.dbt.project import discover_dbt_project
from snowprove.dbt.scan import _load_project_constraints
from snowprove.rewrites.base import VerificationStatus
from snowprove.verifier.backends.builtin import BuiltinVerifierBackend
from snowprove.verifier.backends.qed import QedBackend
from snowprove.verifier.backends.sqlsolver import SqlSolverBackend
from snowprove.verifier.backends.verieql import VeriEqlBackend
from snowprove.verifier.pair_reduction import reduce_pair


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundles_dir", type=Path, nargs="?")
    parser.add_argument("--project", type=Path)
    parser.add_argument(
        "--constraints",
        type=Path,
        help="Constraint catalog JSON (defaults to BUNDLES_DIR/constraints.json).",
    )
    parser.add_argument("--dialect", default="snowflake")
    parser.add_argument("--verieql-dir", type=Path, default=None)
    parser.add_argument("--solver-command", default=None)
    parser.add_argument("--solver-timeout", type=int, default=60)
    parser.add_argument(
        "--qed",
        action="store_true",
        help="Run the QED prover (configured via SNOWPROVE_QED_* env vars).",
    )
    parser.add_argument("--merge-reports", type=Path, nargs=2, default=None)
    parser.add_argument("--report-file", type=Path, default=None)
    args = parser.parse_args()

    if args.merge_reports:
        return _merge_reports(args.merge_reports, args.report_file)
    if args.bundles_dir is None:
        parser.error("bundles_dir is required unless --merge-reports is used")

    constraints_path = args.constraints or (args.bundles_dir / "constraints.json")
    if args.project is not None:
        project = discover_dbt_project(args.project)
        constraints = _load_project_constraints(project.schema_yml_files)
    elif constraints_path.exists():
        constraints = ConstraintCatalog.model_validate_json(constraints_path.read_text())
    else:
        parser.error("provide --project or a constraints snapshot (constraints.json)")
    builtin = BuiltinVerifierBackend()
    solver = (
        SqlSolverBackend(
            solver_command=args.solver_command, timeout_seconds=args.solver_timeout
        )
        if args.solver_command
        else None
    )
    qed = QedBackend(timeout_seconds=args.solver_timeout) if args.qed else None
    refuter = VeriEqlBackend(verieql_dir=args.verieql_dir) if args.verieql_dir else None

    rows = []
    for metadata_path in sorted(args.bundles_dir.glob("*/metadata.json")):
        bundle_dir = metadata_path.parent
        metadata = json.loads(metadata_path.read_text())
        original_sql = (bundle_dir / metadata["original_path"]).read_text()
        for entry in metadata.get("candidates", []):
            candidate_sql = (bundle_dir / entry["path"]).read_text()
            row = {
                "model": bundle_dir.name,
                "candidate": entry["path"],
                "description": entry.get("description", "")[:120],
            }
            row.update(
                _verify_candidate(
                    original_sql,
                    candidate_sql,
                    constraints,
                    args.dialect,
                    builtin,
                    solver,
                    qed,
                    refuter,
                )
            )
            rows.append(row)
            print(f"{row['bucket']:>12}  {row['model']}/{row['candidate']}", file=sys.stderr)
            if args.report_file and len(rows) % 20 == 0:
                _write_report(args.report_file, rows, args, solver, qed, refuter, partial=True)

    buckets = Counter(row["bucket"] for row in rows)
    total = len(rows)
    if args.report_file:
        _write_report(args.report_file, rows, args, solver, qed, refuter, partial=False)

    print(json.dumps({"candidates": total, **dict(sorted(buckets.items()))}, indent=2))
    alarms = [row for row in rows if row.get("crosscheck_alarm")]
    for row in alarms:
        print(f"ALARM: proven candidate refuted: {row['model']}/{row['candidate']}")
    return 1 if alarms else 0


def _verify_candidate(
    original_sql: str,
    candidate_sql: str,
    constraints,
    dialect: str,
    builtin: BuiltinVerifierBackend,
    solver: SqlSolverBackend | None,
    qed: QedBackend | None,
    refuter: VeriEqlBackend | None,
) -> dict:
    trees = []
    for sql in (original_sql, candidate_sql):
        try:
            trees.append(sqlglot.parse_one(sql, read=dialect))
        except SqlglotError as error:
            return {"bucket": "invalid", "reason": f"Could not parse SQL: {error}"}

    if trees[0] == trees[1]:
        return {"bucket": "identity", "reason": "Candidate is the original modulo formatting."}

    # Provers run on the fragment-diff reduction when one applies: proving
    # the differing CTE bodies equivalent proves the full pair by congruence.
    # Refutations of a reduced pair say nothing about the full pair, so NEQ
    # verdicts only count when no reduction happened.
    reduced = reduce_pair(original_sql, candidate_sql, dialect)
    prover_original, prover_candidate = reduced or (original_sql, candidate_sql)

    builtin_result = builtin.verify(
        prover_original, prover_candidate, constraints, dialect=dialect
    )
    proven = None
    solver_note = {"reduced": reduced is not None}
    if builtin_result.status == VerificationStatus.PROVEN_EQUIVALENT:
        proven = {"prover": "builtin", "rule_name": builtin_result.rule_name,
                  "reason": builtin_result.reason}

    if proven is None and qed is not None:
        qed_result = qed.verify(
            prover_original, prover_candidate, constraints, dialect=dialect
        )
        if qed_result.status == VerificationStatus.PROVEN_EQUIVALENT:
            proven = {"prover": "qed", "reason": qed_result.reason}
        else:
            solver_note = {
                **solver_note,
                "qed_status": qed_result.status.value,
                "qed_reason": qed_result.reason,
            }

    if proven is None and solver is not None:
        solver_result = solver.verify(
            prover_original, prover_candidate, constraints, dialect=dialect
        )
        if solver_result.status == VerificationStatus.PROVEN_EQUIVALENT:
            proven = {"prover": "sqlsolver", "reason": solver_result.reason}
        elif solver_result.status == VerificationStatus.NOT_EQUIVALENT and reduced is None:
            return {"bucket": "refuted", "prover": "sqlsolver", "reason": solver_result.reason}
        else:
            solver_note = {
                **solver_note,
                "solver_status": solver_result.status.value,
                "solver_reason": solver_result.reason,
            }

    if proven is not None:
        row = {"bucket": "proven", **proven, "reduced": reduced is not None}
        if refuter is not None:
            crosscheck = refuter.refute(original_sql, candidate_sql, constraints, dialect=dialect)
            row["crosscheck_status"] = crosscheck.status.value
            row["crosscheck_alarm"] = (
                crosscheck.status == VerificationStatus.NOT_EQUIVALENT
            )
        return row

    if refuter is None:
        return {"bucket": "unknown", "reason": builtin_result.reason, **solver_note}

    refutation = refuter.refute(original_sql, candidate_sql, constraints, dialect=dialect)
    if refutation.status == VerificationStatus.NOT_EQUIVALENT:
        return {
            "bucket": "refuted",
            "reason": refutation.reason,
            "counterexample": (refutation.counterexample or "")[:500],
        }
    if refutation.status == VerificationStatus.UNKNOWN:
        return {"bucket": "bounded_ok", "reason": refutation.reason, **solver_note}
    return {"bucket": "unknown", "reason": refutation.reason, **solver_note}


def _write_report(report_file, rows, args, solver, qed, refuter, partial: bool) -> None:
    buckets = Counter(row["bucket"] for row in rows)
    report = {
        "artifact_type": "llm_candidate_verification",
        "schema_version": 1,
        "dialect": args.dialect,
        "solver_enabled": solver is not None,
        "qed_enabled": qed is not None,
        "refuter_enabled": refuter is not None,
        "partial": partial,
        "candidate_count": len(rows),
        "buckets": dict(sorted(buckets.items())),
        "results": rows,
    }
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(json.dumps(report, indent=2))


_MERGE_PRECEDENCE = ("proven", "refuted", "bounded_ok", "unknown", "identity", "invalid")


def _merge_reports(report_paths: list[Path], report_file: Path | None) -> int:
    reports = [json.loads(path.read_text()) for path in report_paths]
    merged: dict[tuple[str, str], dict] = {}
    conflicts = []
    for report in reports:
        for row in report.get("results", []):
            key = (row["model"], row["candidate"])
            existing = merged.get(key)
            if existing is None:
                merged[key] = dict(row)
                continue
            pair = {existing["bucket"], row["bucket"]}
            if pair == {"proven", "refuted"}:
                conflicts.append(key)
                merged[key] = {**existing, "bucket": "conflict",
                               "reason": "One verifier proved what another refuted."}
                continue
            if _MERGE_PRECEDENCE.index(row["bucket"]) < _MERGE_PRECEDENCE.index(
                existing["bucket"]
            ):
                merged[key] = dict(row)

    rows = [merged[key] for key in sorted(merged)]
    buckets = Counter(row["bucket"] for row in rows)
    report = {
        "artifact_type": "llm_candidate_verification",
        "schema_version": 1,
        "merged_from": [str(path) for path in report_paths],
        "candidate_count": len(rows),
        "buckets": dict(sorted(buckets.items())),
        "results": rows,
    }
    if report_file:
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(json.dumps(report, indent=2))
    print(json.dumps({"candidates": len(rows), **dict(sorted(buckets.items()))}, indent=2))
    for key in conflicts:
        print(f"ALARM: prover/refuter conflict on {key[0]}/{key[1]}")
    return 1 if conflicts else 0


if __name__ == "__main__":
    sys.exit(main())
