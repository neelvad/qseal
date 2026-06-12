# Verify LLM candidate bundles produced by scripts/generate_llm_candidates.py.
#
# Cascade, cheapest first: parse -> identity filter -> builtin prover ->
# VeriEQL refutation of non-proven survivors and cross-check of proven ones.
# Acceptance is PROVEN_EQUIVALENT only; bounded-OK is evidence, never a proof.
#
#   uv run python scripts/verify_llm_candidates.py BUNDLES_DIR --project PROJECT \
#       [--verieql-dir ~/workspace/snowprove-eval/VeriEQL] [--dialect snowflake]
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import sqlglot
from sqlglot.errors import SqlglotError

from snowprove.dbt.project import discover_dbt_project
from snowprove.dbt.scan import _load_project_constraints
from snowprove.rewrites.base import VerificationStatus
from snowprove.verifier.backends.builtin import BuiltinVerifierBackend
from snowprove.verifier.backends.verieql import VeriEqlBackend


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundles_dir", type=Path)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--dialect", default="snowflake")
    parser.add_argument("--verieql-dir", type=Path, default=None)
    parser.add_argument("--report-file", type=Path, default=None)
    args = parser.parse_args()

    project = discover_dbt_project(args.project)
    constraints = _load_project_constraints(project.schema_yml_files)
    builtin = BuiltinVerifierBackend()
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
                    original_sql, candidate_sql, constraints, args.dialect, builtin, refuter
                )
            )
            rows.append(row)
            print(f"{row['bucket']:>12}  {row['model']}/{row['candidate']}", file=sys.stderr)

    buckets = Counter(row["bucket"] for row in rows)
    total = len(rows)
    report = {
        "artifact_type": "llm_candidate_verification",
        "schema_version": 1,
        "dialect": args.dialect,
        "refuter_enabled": refuter is not None,
        "candidate_count": total,
        "buckets": dict(sorted(buckets.items())),
        "results": rows,
    }
    if args.report_file:
        args.report_file.parent.mkdir(parents=True, exist_ok=True)
        args.report_file.write_text(json.dumps(report, indent=2))

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

    builtin_result = builtin.verify(original_sql, candidate_sql, constraints, dialect=dialect)
    if builtin_result.status == VerificationStatus.PROVEN_EQUIVALENT:
        row = {
            "bucket": "proven",
            "rule_name": builtin_result.rule_name,
            "reason": builtin_result.reason,
        }
        if refuter is not None:
            crosscheck = refuter.refute(original_sql, candidate_sql, constraints, dialect=dialect)
            row["crosscheck_status"] = crosscheck.status.value
            row["crosscheck_alarm"] = (
                crosscheck.status == VerificationStatus.NOT_EQUIVALENT
            )
        return row

    if refuter is None:
        return {"bucket": "unknown", "reason": builtin_result.reason}

    refutation = refuter.refute(original_sql, candidate_sql, constraints, dialect=dialect)
    if refutation.status == VerificationStatus.NOT_EQUIVALENT:
        return {
            "bucket": "refuted",
            "reason": refutation.reason,
            "counterexample": (refutation.counterexample or "")[:500],
        }
    if refutation.status == VerificationStatus.UNKNOWN:
        return {"bucket": "bounded_ok", "reason": refutation.reason}
    return {"bucket": "unknown", "reason": refutation.reason}


if __name__ == "__main__":
    sys.exit(main())
