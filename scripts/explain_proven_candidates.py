# Tier-2 performance evidence: Snowflake EXPLAIN plan diffing for proven pairs.
#
# Replays extracted schemas as empty tables in a scratch database (EXPLAIN is
# compile-only: no warehouse runtime, no credits beyond cloud services), runs
# EXPLAIN USING JSON on both sides of each proven rewrite, and diffs the
# operator trees. Plan-node deltas are work-eliminated evidence on the actual
# target engine.
#
#   uv run python scripts/explain_proven_candidates.py REPORT.json BUNDLES_DIR \
#       --report-file explain.json
import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from snowprove.constraints.model import ConstraintCatalog
from snowprove.verifier.backends.qed import _string_typed_columns
from snowprove.verifier.backends.sqlsolver import _unqualify_relations
from snowprove.verifier.backends.verieql import collect_pair_schema

DATABASE = "SNOWPROVE_TIER2"

_DATE_FUNCTIONS = {
    "date_trunc": ("this",),
    "dateadd": ("this",),
    "datediff": ("this", "expression"),
    "year": ("this",),
    "month": ("this",),
    "day": ("this",),
    "last_day": ("this",),
    "to_date": (),
    "date_part": ("this",),
}
_STRING_FUNCTIONS = {
    "lower", "upper", "trim", "ltrim", "rtrim", "length", "substring", "substr",
    "split_part", "concat", "replace", "left", "right", "initcap", "like", "ilike",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_path", type=Path)
    parser.add_argument("bundles_dir", type=Path)
    parser.add_argument("--report-file", type=Path, required=True)
    parser.add_argument("--dialect", default="snowflake")
    parser.add_argument("--only", default=None)
    args = parser.parse_args()

    import snowflake.connector

    connection = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        login_timeout=30,
    )
    cursor = connection.cursor()
    cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DATABASE}")
    cursor.execute(f"USE DATABASE {DATABASE}")
    cursor.execute("CREATE SCHEMA IF NOT EXISTS PAIRS")
    cursor.execute("USE SCHEMA PAIRS")

    report = json.loads(args.report_path.read_text())
    constraints = ConstraintCatalog.model_validate_json(
        (args.bundles_dir / "constraints.json").read_text()
    )
    only = set(args.only.split(",")) if args.only else None

    rows = []
    proven = [row for row in report["results"] if row["bucket"] == "proven"]
    for row in proven:
        if only is not None and row["model"] not in only:
            continue
        bundle = args.bundles_dir / row["model"]
        record = {"model": row["model"], "candidate": row["candidate"],
                  "prover": row.get("prover")}
        record.update(
            _explain_pair(
                cursor,
                (bundle / "original.sql").read_text(),
                (bundle / row["candidate"]).read_text(),
                constraints,
                args.dialect,
            )
        )
        rows.append(record)
        print(f"{record['verdict']:>18}  {row['model']}/{row['candidate']}", file=sys.stderr)
        if len(rows) % 20 == 0:
            _write(args.report_file, rows, partial=True)

    _write(args.report_file, rows, partial=False)
    verdicts = Counter(record["verdict"] for record in rows)
    print(json.dumps({"pairs": len(rows), **dict(sorted(verdicts.items()))}, indent=2))
    connection.close()
    return 0


def _explain_pair(cursor, original, candidate, constraints, dialect) -> dict:
    normalized = _unqualify_relations(original, candidate, dialect)
    if normalized is None:
        return {"verdict": "error", "reason": "relation name collision"}
    try:
        trees = [sqlglot.parse_one(sql, read=dialect) for sql in normalized]
    except SqlglotError as error:
        return {"verdict": "error", "reason": str(error)[:160]}

    schema = collect_pair_schema(trees, constraints)
    if isinstance(schema, str):
        return {"verdict": "error", "reason": schema[:160]}

    try:
        for statement in _ddl(schema, constraints, trees):
            cursor.execute(statement)
        plans = []
        for sql in normalized:
            cursor.execute(f"EXPLAIN USING JSON {sql.rstrip().rstrip(';')}")
            plans.append(json.loads(cursor.fetchone()[0]))
    except Exception as error:  # noqa: BLE001 - record and continue
        return {"verdict": "error", "reason": str(error)[:200]}

    return _diff_plans(*plans)


def _ddl(schema, constraints, trees) -> list[str]:
    varchar_columns = _string_typed_columns(trees) | _function_arg_columns(
        trees, _STRING_FUNCTIONS
    )
    date_columns = _date_arg_columns(trees) - varchar_columns
    statements = []
    for table_name in sorted(schema):
        column_set = {column.lower() for column in schema[table_name]}
        table = constraints.table(table_name.lower())
        if table is not None:
            column_set.update(
                column
                for column, constraint in table.columns.items()
                if constraint.nullable is False
            )
            for key in table.unique:
                column_set.update(key)
        definitions = []
        for column in sorted(column_set) or ["snowprove_id"]:
            if column in varchar_columns:
                column_type = "VARCHAR"
            elif column in date_columns:
                column_type = "TIMESTAMP_NTZ"
            else:
                column_type = "NUMBER"
            definitions.append(f"{column} {column_type}")
        statements.append(
            f"CREATE OR REPLACE TABLE {table_name} ({', '.join(definitions)})"
        )
    return statements


def _function_arg_columns(trees, function_names) -> set[str]:
    names: set[str] = set()
    for tree in trees:
        for node in tree.walk():
            if isinstance(node, exp.Func) and node.sql_name().lower() in function_names:
                for argument in node.args.values():
                    if isinstance(argument, exp.Column):
                        names.add(argument.name.lower())
    return names


def _date_arg_columns(trees) -> set[str]:
    names: set[str] = set()
    for tree in trees:
        for node in tree.walk():
            if not isinstance(node, exp.Func):
                continue
            arg_keys = _DATE_FUNCTIONS.get(node.sql_name().lower())
            if arg_keys is None:
                continue
            for key in arg_keys or node.args.keys():
                argument = node.args.get(key)
                if isinstance(argument, exp.Column):
                    names.add(argument.name.lower())
    return names


_OPERATION_GROUPS = {
    "join": ("join",),
    "aggregate": ("aggregate", "groupingsets", "windowfunction", "sort"),
    "filter": ("filter",),
    "scan": ("tablescan",),
}


def _plan_profile(plan: dict) -> Counter:
    counts: Counter = Counter()
    for step in plan.get("Operations", []) or []:
        operations = step if isinstance(step, list) else [step]
        for operation in operations:
            kind = str(operation.get("operation", "")).lower()
            for group, members in _OPERATION_GROUPS.items():
                if kind in members:
                    counts[group] += 1
    return counts


def _diff_plans(original_plan: dict, candidate_plan: dict) -> dict:
    before = _plan_profile(original_plan)
    after = _plan_profile(candidate_plan)
    deltas = {
        group: after.get(group, 0) - before.get(group, 0)
        for group in _OPERATION_GROUPS
        if after.get(group, 0) != before.get(group, 0)
    }
    if not deltas:
        verdict = "no_plan_change"
    elif all(delta < 0 for delta in deltas.values()):
        verdict = "work_eliminated"
    elif all(delta > 0 for delta in deltas.values()):
        verdict = "work_added"
    else:
        verdict = "mixed_change"
    return {
        "verdict": verdict,
        "deltas": deltas,
        "before": dict(before),
        "after": dict(after),
    }


def _write(report_file: Path, rows: list[dict], partial: bool) -> None:
    verdicts = Counter(row["verdict"] for row in rows)
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(
        json.dumps(
            {
                "artifact_type": "proven_candidate_explain_diffs",
                "schema_version": 1,
                "engine": "snowflake",
                "partial": partial,
                "pair_count": len(rows),
                "verdicts": dict(sorted(verdicts.items())),
                "results": rows,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
