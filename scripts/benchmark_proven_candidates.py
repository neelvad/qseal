# Tier-1 performance evidence: DuckDB micro-benchmarks for proven candidates.
#
# For each proven rewrite, synthesize schema-conforming data (respecting the
# trusted unique/not-null constraints), transpile the Snowflake pair to
# DuckDB, and run the existing benchmark harness. Results are indicative,
# not predictive: synthetic distributions are not production distributions,
# and DuckDB's optimizer is not Snowflake's.
#
#   uv run python scripts/benchmark_proven_candidates.py REPORT.json BUNDLES_DIR \
#       --report-file bench.json --rows 1000000
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from snowprove.benchmark import BenchmarkStatus, benchmark_query_pair
from snowprove.constraints.model import ConstraintCatalog
from snowprove.verifier.backends.qed import _string_typed_columns
from snowprove.verifier.backends.sqlsolver import _unqualify_relations
from snowprove.verifier.backends.verieql import collect_pair_schema

FILLER_STRINGS = ("snowprove_filler_a", "snowprove_filler_b", "snowprove_filler_c")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_path", type=Path)
    parser.add_argument("bundles_dir", type=Path)
    parser.add_argument("--report-file", type=Path, required=True)
    parser.add_argument("--rows", default="100000,1000000")
    parser.add_argument("--dialect", default="snowflake")
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--only", default=None)
    args = parser.parse_args()

    scales = [int(float(scale)) for scale in args.rows.split(",")]
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
        original = (bundle / "original.sql").read_text()
        candidate = (bundle / row["candidate"]).read_text()
        for scale in scales:
            record = {
                "model": row["model"],
                "candidate": row["candidate"],
                "prover": row.get("prover"),
                "rows": scale,
            }
            record.update(
                _benchmark_pair(original, candidate, constraints, args, scale)
            )
            rows.append(record)
            print(
                f"{record.get('outcome', '?'):>10}  {row['model']}/{row['candidate']}"
                f" @ {scale}: speedup={record.get('speedup')}",
                file=sys.stderr,
            )
            if len(rows) % 10 == 0:
                _write(args.report_file, rows, partial=True)

    _write(args.report_file, rows, partial=False)
    outcomes = Counter(record["outcome"] for record in rows)
    print(json.dumps({"measurements": len(rows), **dict(sorted(outcomes.items()))}, indent=2))
    return 0


def _benchmark_pair(original, candidate, constraints, args, scale) -> dict:
    normalized = _unqualify_relations(original, candidate, args.dialect)
    if normalized is None:
        return {"outcome": "error", "reason": "relation name collision"}
    try:
        trees = [sqlglot.parse_one(sql, read=args.dialect) for sql in normalized]
        duckdb_pair = [
            sqlglot.transpile(sql, read=args.dialect, write="duckdb")[0]
            for sql in normalized
        ]
    except SqlglotError as error:
        return {"outcome": "error", "reason": f"transpile: {str(error)[:160]}"}

    schema = collect_pair_schema(trees, constraints)
    if isinstance(schema, str):
        return {"outcome": "error", "reason": schema[:160]}

    setup_sql = _setup_sql(schema, constraints, trees, scale)
    try:
        result = benchmark_query_pair(
            duckdb_pair[0],
            duckdb_pair[1],
            setup_sql=setup_sql,
            warmups=args.warmups,
            repetitions=args.repetitions,
            timeout_seconds=args.timeout,
        )
    except Exception as error:  # noqa: BLE001 - record and continue the sweep
        return {"outcome": "error", "reason": str(error)[:160]}

    if result.status != BenchmarkStatus.COMPLETED:
        reason = None
        for side in (result.original, result.rewritten):
            if side is not None and side.error:
                reason = side.error
                break
        return {"outcome": "failed", "reason": (reason or result.status.value)[:160]}

    original_rows = getattr(result.original, "row_count", None)
    rewritten_rows = getattr(result.rewritten, "row_count", None)
    if original_rows is not None and rewritten_rows is not None and original_rows != rewritten_rows:
        # The pair is proven equivalent, so differing row counts can only mean
        # the synthetic data violated the trusted premises.
        return {
            "outcome": "suspect",
            "reason": f"row counts differ ({original_rows} vs {rewritten_rows}); "
            "synthetic data violates premises",
        }

    speedup = result.speedup
    if speedup is None:
        return {"outcome": "failed", "reason": "no timing (per-query timeout likely)"}
    elif speedup >= 1.2:
        outcome = "faster"
    elif speedup <= 1 / 1.2:
        outcome = "slower"
    else:
        outcome = "neutral"
    return {
        "outcome": outcome,
        "speedup": round(speedup, 3) if speedup is not None else None,
        "original_ms": result.original.median_ms,
        "rewritten_ms": result.rewritten.median_ms,
    }


_STRING_FUNCTIONS = {
    "lower", "upper", "trim", "ltrim", "rtrim", "length", "substring", "substr",
    "split_part", "concat", "replace", "left", "right", "initcap", "like",
}


def _string_function_columns(trees) -> set[str]:
    """Columns passed to string functions get varchar synthetic data."""
    names: set[str] = set()
    for tree in trees:
        for node in tree.walk():
            if not isinstance(node, exp.Func):
                continue
            if node.sql_name().lower() not in _STRING_FUNCTIONS:
                continue
            for argument in node.args.values():
                if isinstance(argument, exp.Column):
                    names.add(argument.name.lower())
    return names


def _setup_sql(schema, constraints, trees, scale: int) -> str:
    varchar_columns = _string_typed_columns(trees) | _string_function_columns(trees)
    pool = _string_pool(trees)
    statements = []
    for seed, table_name in enumerate(sorted(schema)):
        column_set = {column.lower() for column in schema[table_name]}
        table = constraints.table(table_name.lower())
        non_null: set[str] = set()
        unique_columns: set[str] = set()
        if table is not None:
            non_null = {
                column
                for column, constraint in table.columns.items()
                if constraint.nullable is False
            }
            for key in table.unique:
                if all(column in non_null for column in key):
                    unique_columns.update(key)
            # Constraint columns must exist in the data or the synthetic
            # database silently violates the premises the proof relies on.
            column_set.update(unique_columns)
            column_set.update(non_null)
        columns = sorted(column_set)

        expressions = []
        for index, column in enumerate(columns or ["snowprove_id"]):
            mix = seed * 97 + index * 13 + 7
            if column in unique_columns:
                value = "i"
            elif column in varchar_columns:
                value = (
                    f"(list_value({pool}))[1 + (hash(i * {mix}) % {pool.count(',') + 1})::INT]"
                )
            else:
                value = f"(hash(i * {mix}) % 1000)::BIGINT"
            if column not in non_null and column not in unique_columns:
                value = f"CASE WHEN hash(i * {mix + 1}) % 10 = 0 THEN NULL ELSE {value} END"
            expressions.append(f"{value} AS {column}")

        statements.append(
            f"CREATE TABLE {table_name.lower()} AS "
            f"SELECT {', '.join(expressions)} FROM range({scale}) t(i);"
        )
    return "\n".join(statements)


def _string_pool(trees) -> str:
    literals: list[str] = []
    for tree in trees:
        for node in tree.find_all(exp.Literal):
            if node.is_string and node.this not in literals and len(node.this) < 40:
                literals.append(node.this)
    pool = [*literals[:20], *FILLER_STRINGS]
    escaped = ", ".join("'" + value.replace("'", "''") + "'" for value in pool)
    return escaped


def _write(report_file: Path, rows: list[dict], partial: bool) -> None:
    outcomes = Counter(row["outcome"] for row in rows)
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(
        json.dumps(
            {
                "artifact_type": "proven_candidate_benchmarks",
                "schema_version": 1,
                "engine": "duckdb",
                "partial": partial,
                "measurement_count": len(rows),
                "outcomes": dict(sorted(outcomes.items())),
                "results": rows,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
