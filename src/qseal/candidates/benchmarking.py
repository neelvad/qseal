"""Tier-1 performance evidence: DuckDB micro-benchmarks for proven candidates.

For each proven rewrite, synthesize schema-conforming data (respecting the
trusted unique/not-null constraints), transpile the pair to DuckDB, and run
the benchmark harness. Results are indicative, not predictive: synthetic
distributions are not production distributions, and DuckDB's optimizer is not
Snowflake's. A row-count mismatch between the proven-equivalent sides flags
premise-violating synthetic data.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from qseal.benchmark import BenchmarkStatus, benchmark_query_pair
from qseal.constraints.model import ConstraintCatalog
from qseal.verifier.backends.qed import _string_typed_columns
from qseal.verifier.backends.sqlsolver import _unqualify_relations
from qseal.verifier.backends.verieql import collect_pair_schema

Logger = Callable[[str], None]
FILLER_STRINGS = ("qseal_filler_a", "qseal_filler_b", "qseal_filler_c")
_STRING_FUNCTIONS = {
    "lower", "upper", "trim", "ltrim", "rtrim", "length", "substring", "substr",
    "split_part", "concat", "replace", "left", "right", "initcap", "like",
}


def benchmark_proven(
    report_path: Path,
    bundles_dir: Path,
    *,
    rows: list[int],
    dialect: str = "snowflake",
    warmups: int = 1,
    repetitions: int = 3,
    timeout: float = 30.0,
    only: set[str] | None = None,
    report_file: Path | None = None,
    log: Logger | None = None,
) -> dict:
    """Benchmark every proven rewrite in a verification report; returns counts."""
    log = log or (lambda _message: None)
    report = json.loads(report_path.read_text())
    constraints = ConstraintCatalog.model_validate_json(
        (bundles_dir / "constraints.json").read_text()
    )

    records: list[dict] = []
    for row in report["results"]:
        if row["bucket"] != "proven":
            continue
        if only is not None and row["model"] not in only:
            continue
        bundle = bundles_dir / row["model"]
        original = (bundle / "original.sql").read_text()
        candidate = (bundle / row["candidate"]).read_text()
        for scale in rows:
            record = {"model": row["model"], "candidate": row["candidate"],
                      "prover": row.get("prover"), "rows": scale}
            record.update(
                benchmark_pair(
                    original, candidate, constraints,
                    dialect=dialect, scale=scale,
                    warmups=warmups, repetitions=repetitions, timeout=timeout,
                )
            )
            records.append(record)
            log(f"{record.get('outcome', '?'):>10}  {row['model']}/{row['candidate']}"
                f" @ {scale}: speedup={record.get('speedup')}")
            if report_file is not None and len(records) % 10 == 0:
                _write(report_file, records, partial=True)

    if report_file is not None:
        _write(report_file, records, partial=False)
    return {
        "measurement_count": len(records),
        "outcomes": dict(sorted(Counter(r["outcome"] for r in records).items())),
        "results": records,
    }


def benchmark_pair(
    original: str,
    candidate: str,
    constraints: ConstraintCatalog,
    *,
    dialect: str,
    scale: int,
    warmups: int,
    repetitions: int,
    timeout: float,
) -> dict:
    normalized = _unqualify_relations(original, candidate, dialect)
    if normalized is None:
        return {"outcome": "error", "reason": "relation name collision"}
    try:
        trees = [sqlglot.parse_one(sql, read=dialect) for sql in normalized]
        duckdb_pair = [
            sqlglot.transpile(sql, read=dialect, write="duckdb")[0] for sql in normalized
        ]
    except SqlglotError as error:
        return {"outcome": "error", "reason": f"transpile: {str(error)[:160]}"}

    schema = collect_pair_schema(trees, constraints)
    if isinstance(schema, str):
        return {"outcome": "error", "reason": schema[:160]}

    setup_sql = _setup_sql(schema, constraints, trees, scale)
    try:
        result = benchmark_query_pair(
            duckdb_pair[0], duckdb_pair[1], setup_sql=setup_sql,
            warmups=warmups, repetitions=repetitions, timeout_seconds=timeout,
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
    if speedup >= 1.2:
        outcome = "faster"
    elif speedup <= 1 / 1.2:
        outcome = "slower"
    else:
        outcome = "neutral"
    return {
        "outcome": outcome,
        "speedup": round(speedup, 3),
        "original_ms": result.original.median_ms,
        "rewritten_ms": result.rewritten.median_ms,
    }


def _string_function_columns(trees) -> set[str]:
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
        for index, column in enumerate(columns or ["qseal_id"]):
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
    return ", ".join("'" + value.replace("'", "''") + "'" for value in pool)


def _write(report_file: Path, rows: list[dict], partial: bool) -> None:
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(
        json.dumps(
            {
                "artifact_type": "proven_candidate_benchmarks",
                "schema_version": 1,
                "engine": "duckdb",
                "partial": partial,
                "measurement_count": len(rows),
                "outcomes": dict(sorted(Counter(r["outcome"] for r in rows).items())),
                "results": rows,
            },
            indent=2,
        )
    )
