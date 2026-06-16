# Thin shim for `qseal llm verify` / `qseal llm merge`; kept for the
# Modal app and the SQLSolver container wrapper, which invoke this path.
# All logic lives in qseal.candidates.verification.
import argparse
import json
import sys
from pathlib import Path

from qseal.candidates.verification import merge_reports, verify_bundles
from qseal.constraints.model import ConstraintCatalog
from qseal.dbt.project import discover_dbt_project
from qseal.dbt.scan import _load_project_constraints
from qseal.verifier.backends.qed import QedBackend
from qseal.verifier.backends.sqlsolver import SqlSolverBackend
from qseal.verifier.backends.verieql import VeriEqlBackend


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundles_dir", type=Path, nargs="?")
    parser.add_argument("--project", type=Path)
    parser.add_argument("--constraints", type=Path)
    parser.add_argument("--dialect", default="snowflake")
    parser.add_argument("--verieql-dir", type=Path, default=None)
    parser.add_argument("--solver-command", default=None)
    parser.add_argument("--solver-timeout", type=int, default=60)
    parser.add_argument("--qed", action="store_true")
    parser.add_argument("--merge-reports", type=Path, nargs=2, default=None)
    parser.add_argument("--only", default=None)
    parser.add_argument("--report-file", type=Path, default=None)
    args = parser.parse_args()

    if args.merge_reports:
        result = merge_reports(list(args.merge_reports), args.report_file)
        print(json.dumps({"candidates": result["candidate_count"], **result["buckets"]}, indent=2))
        for conflict in result["conflicts"]:
            print(f"ALARM: prover/refuter conflict on {conflict}")
        return 1 if result["conflicts"] else 0

    if args.bundles_dir is None:
        parser.error("bundles_dir is required unless --merge-reports is used")

    if args.project is not None:
        constraints = _load_project_constraints(
            discover_dbt_project(args.project).schema_yml_files
        )
    else:
        path = args.constraints or (args.bundles_dir / "constraints.json")
        if not path.exists():
            parser.error("provide --project or a constraints snapshot (constraints.json)")
        constraints = ConstraintCatalog.model_validate_json(path.read_text())

    result = verify_bundles(
        args.bundles_dir,
        constraints,
        dialect=args.dialect,
        solver=(
            SqlSolverBackend(
                solver_command=args.solver_command, timeout_seconds=args.solver_timeout
            )
            if args.solver_command
            else None
        ),
        qed=QedBackend(timeout_seconds=args.solver_timeout) if args.qed else None,
        refuter=VeriEqlBackend(verieql_dir=args.verieql_dir) if args.verieql_dir else None,
        only=set(args.only.split(",")) if args.only else None,
        report_file=args.report_file,
        log=lambda message: print(message, file=sys.stderr),
    )
    print(json.dumps({"candidates": result["candidate_count"], **result["buckets"]}, indent=2))
    for alarm in result["alarms"]:
        print(f"ALARM: proven candidate refuted: {alarm}")
    return 1 if result["alarms"] else 0


if __name__ == "__main__":
    sys.exit(main())
