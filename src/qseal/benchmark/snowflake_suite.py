from __future__ import annotations

import json
import statistics
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from qseal.benchmark.model import BenchmarkResult, BenchmarkStatus
from qseal.benchmark.snowflake import (
    ConnectorFactory,
    SnowflakeConnectionConfig,
    benchmark_query_pair,
)

SNOWFLAKE_FAMILY_SUITE_ID = "snowflake-family-v1"
SnowflakeFamilyMode = Literal["aggregate", "materialized"]


class SnowflakeFamilyCaseSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    rewrite_family: str
    mode: SnowflakeFamilyMode
    scale_rows: int
    evidence_scope: str
    description: str
    setup_sql: str
    original_sql: str
    rewritten_sql: str


class SnowflakeFamilyCaseSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    rewrite_family: str
    mode: SnowflakeFamilyMode
    scale_rows: int
    run_index: int
    status: BenchmarkStatus
    classification: str
    evidence_scope: str
    notes: tuple[str, ...] = Field(default_factory=tuple)
    reason: str | None = None
    original_median_ms: float | None = None
    rewritten_median_ms: float | None = None
    wall_speedup: float | None = None
    original_execution_median_ms: float | None = None
    rewritten_execution_median_ms: float | None = None
    execution_speedup: float | None = None
    original_bytes_scanned: int = 0
    rewritten_bytes_scanned: int = 0
    row_counts_match: bool | None = None
    timing_confident: bool = True
    plan_counts: dict[str, dict[str, int]] = Field(default_factory=dict)
    benchmark_report_path: str
    setup_path: str
    original_path: str
    rewritten_path: str


class SnowflakeFamilyCaseResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    spec: SnowflakeFamilyCaseSpec
    run_index: int
    summary: SnowflakeFamilyCaseSummary
    benchmark: BenchmarkResult


class SnowflakeFamilySuiteReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    artifact_type: str = "snowflake_family_benchmark_suite"
    suite_id: str = SNOWFLAKE_FAMILY_SUITE_ID
    output_dir: str
    runs: int
    modes: tuple[SnowflakeFamilyMode, ...]
    scales: tuple[int, ...]
    warmups: int
    repetitions: int
    timeout_seconds: float
    minimum_duration_ms: float
    materialized_limit: int
    query_tag_prefix: str
    result_count: int
    completed_count: int
    classification_counts: dict[str, int]
    summaries: tuple[SnowflakeFamilyCaseSummary, ...]
    results: tuple[SnowflakeFamilyCaseResult, ...]


def snowflake_family_cases(
    *,
    scales: Sequence[int] = (1_000_000,),
    modes: Sequence[SnowflakeFamilyMode] = ("aggregate",),
    materialized_limit: int = 10_000,
) -> tuple[SnowflakeFamilyCaseSpec, ...]:
    _validate_case_settings(scales, modes, materialized_limit)
    cases = []
    for scale_rows in scales:
        for mode in modes:
            for definition in _family_definitions(scale_rows):
                original_sql = _shape_query(
                    definition["original_sql"],
                    mode=mode,
                    materialized_limit=materialized_limit,
                )
                rewritten_sql = _shape_query(
                    definition["rewritten_sql"],
                    mode=mode,
                    materialized_limit=materialized_limit,
                )
                cases.append(
                    SnowflakeFamilyCaseSpec(
                        case_id=f"{mode}-{_scale_slug(scale_rows)}-{definition['id']}",
                        rewrite_family=definition["id"],
                        mode=mode,
                        scale_rows=scale_rows,
                        evidence_scope=(
                            "aggregate_query"
                            if mode == "aggregate"
                            else "bounded_materialized_output"
                        ),
                        description=definition["description"],
                        setup_sql=definition["setup_sql"],
                        original_sql=original_sql,
                        rewritten_sql=rewritten_sql,
                    )
                )
    return tuple(cases)


def run_snowflake_family_suite(
    output_dir: Path,
    *,
    scales: Sequence[int] = (1_000_000,),
    modes: Sequence[SnowflakeFamilyMode] = ("aggregate",),
    runs: int = 1,
    warmups: int = 1,
    repetitions: int = 3,
    timeout_seconds: float = 30.0,
    minimum_duration_ms: float = 0.0,
    materialized_limit: int = 10_000,
    query_tag_prefix: str = "qseal-tier3-family",
    config: SnowflakeConnectionConfig | None = None,
    connector_factory: ConnectorFactory | None = None,
) -> SnowflakeFamilySuiteReport:
    if runs < 1:
        raise ValueError("runs must be one or greater.")
    cases = snowflake_family_cases(
        scales=scales,
        modes=modes,
        materialized_limit=materialized_limit,
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    results: list[SnowflakeFamilyCaseResult] = []
    summaries: list[SnowflakeFamilyCaseSummary] = []
    for run_index in range(1, runs + 1):
        for spec in cases:
            case_dir = _case_dir(output_dir, spec, run_index)
            case_dir.mkdir(parents=True, exist_ok=True)
            setup_path = case_dir / "setup.sql"
            original_path = case_dir / "original.sql"
            rewritten_path = case_dir / "rewritten.sql"
            benchmark_report_path = case_dir / "benchmark.json"

            setup_path.write_text(f"{spec.setup_sql.strip()}\n")
            original_path.write_text(f"{spec.original_sql.strip()}\n")
            rewritten_path.write_text(f"{spec.rewritten_sql.strip()}\n")

            benchmark = benchmark_query_pair(
                spec.original_sql,
                spec.rewritten_sql,
                setup_sql=spec.setup_sql,
                warmups=warmups,
                repetitions=repetitions,
                timeout_seconds=timeout_seconds,
                minimum_duration_ms=minimum_duration_ms,
                query_tag=f"{query_tag_prefix}-{spec.case_id}-run-{run_index:03d}",
                config=config,
                connector_factory=connector_factory,
            ).model_copy(
                update={
                    "inputs": {
                        "engine": "snowflake",
                        "suite_id": SNOWFLAKE_FAMILY_SUITE_ID,
                        "case_id": spec.case_id,
                        "rewrite_family": spec.rewrite_family,
                        "mode": spec.mode,
                        "scale_rows": str(spec.scale_rows),
                        "run_index": str(run_index),
                        "setup_path": str(setup_path),
                        "original_path": str(original_path),
                        "rewritten_path": str(rewritten_path),
                    }
                }
            )
            benchmark_report_path.write_text(
                f"{_benchmark_json(benchmark)}\n",
            )

            summary = summarize_snowflake_family_case(
                spec,
                run_index=run_index,
                benchmark=benchmark,
                benchmark_report_path=benchmark_report_path,
                setup_path=setup_path,
                original_path=original_path,
                rewritten_path=rewritten_path,
            )
            summaries.append(summary)
            results.append(
                SnowflakeFamilyCaseResult(
                    spec=spec,
                    run_index=run_index,
                    summary=summary,
                    benchmark=benchmark,
                )
            )

    return SnowflakeFamilySuiteReport(
        output_dir=str(output_dir),
        runs=runs,
        modes=tuple(modes),
        scales=tuple(scales),
        warmups=warmups,
        repetitions=repetitions,
        timeout_seconds=timeout_seconds,
        minimum_duration_ms=minimum_duration_ms,
        materialized_limit=materialized_limit,
        query_tag_prefix=query_tag_prefix,
        result_count=len(results),
        completed_count=sum(
            result.benchmark.status == BenchmarkStatus.COMPLETED for result in results
        ),
        classification_counts=_classification_counts(summaries),
        summaries=tuple(summaries),
        results=tuple(results),
    )


def summarize_snowflake_family_case(
    spec: SnowflakeFamilyCaseSpec,
    *,
    run_index: int,
    benchmark: BenchmarkResult,
    benchmark_report_path: Path,
    setup_path: Path,
    original_path: Path,
    rewritten_path: Path,
) -> SnowflakeFamilyCaseSummary:
    original_execution_ms = _median(benchmark.original.execution_time_ms)
    rewritten_execution_ms = _median(benchmark.rewritten.execution_time_ms)
    execution_speedup = _speedup(original_execution_ms, rewritten_execution_ms)
    original_bytes = sum(benchmark.original.bytes_scanned)
    rewritten_bytes = sum(benchmark.rewritten.bytes_scanned)
    classification = _classify_result(
        benchmark,
        original_execution_ms=original_execution_ms,
        rewritten_execution_ms=rewritten_execution_ms,
        execution_speedup=execution_speedup,
        original_bytes=original_bytes,
        rewritten_bytes=rewritten_bytes,
    )
    return SnowflakeFamilyCaseSummary(
        case_id=spec.case_id,
        rewrite_family=spec.rewrite_family,
        mode=spec.mode,
        scale_rows=spec.scale_rows,
        run_index=run_index,
        status=benchmark.status,
        classification=classification,
        evidence_scope=spec.evidence_scope,
        notes=_case_notes(
            spec,
            benchmark,
            classification=classification,
            original_execution_ms=original_execution_ms,
            rewritten_execution_ms=rewritten_execution_ms,
            original_bytes=original_bytes,
            rewritten_bytes=rewritten_bytes,
        ),
        reason=benchmark.reason,
        original_median_ms=benchmark.original.median_ms,
        rewritten_median_ms=benchmark.rewritten.median_ms,
        wall_speedup=benchmark.speedup,
        original_execution_median_ms=original_execution_ms,
        rewritten_execution_median_ms=rewritten_execution_ms,
        execution_speedup=execution_speedup,
        original_bytes_scanned=original_bytes,
        rewritten_bytes_scanned=rewritten_bytes,
        row_counts_match=benchmark.row_counts_match,
        timing_confident=benchmark.timing_confident,
        plan_counts=_plan_counts(benchmark),
        benchmark_report_path=str(benchmark_report_path),
        setup_path=str(setup_path),
        original_path=str(original_path),
        rewritten_path=str(rewritten_path),
    )


def _family_definitions(scale_rows: int) -> tuple[dict[str, str], ...]:
    orders = scale_rows * 2
    return (
        {
            "id": "distinct",
            "description": "Remove redundant DISTINCT from a unique user_id projection.",
            "setup_sql": _users_setup(scale_rows),
            "original_sql": "SELECT DISTINCT user_id FROM qseal_users",
            "rewritten_sql": "SELECT user_id FROM qseal_users",
        },
        {
            "id": "not_null",
            "description": "Remove redundant IS NOT NULL from a generated non-null key.",
            "setup_sql": _users_setup(scale_rows),
            "original_sql": (
                "SELECT user_id FROM qseal_users WHERE user_id IS NOT NULL"
            ),
            "rewritten_sql": "SELECT user_id FROM qseal_users",
        },
        {
            "id": "left_join",
            "description": "Remove an unused one-to-one LEFT JOIN under a uniqueness premise.",
            "setup_sql": f"{_users_setup(scale_rows)}\n{_profiles_setup(scale_rows)}",
            "original_sql": (
                "SELECT u.user_id "
                "FROM qseal_users AS u "
                "LEFT JOIN qseal_profiles AS p ON u.user_id = p.user_id"
            ),
            "rewritten_sql": "SELECT u.user_id FROM qseal_users AS u",
        },
        {
            "id": "exists",
            "description": "Rewrite JOIN DISTINCT into a semijoin-style EXISTS query.",
            "setup_sql": f"{_users_id_setup(scale_rows)}\n{_orders_setup(orders, scale_rows)}",
            "original_sql": (
                "SELECT DISTINCT u.user_id "
                "FROM qseal_users AS u "
                "INNER JOIN qseal_orders AS o ON u.user_id = o.user_id"
            ),
            "rewritten_sql": (
                "SELECT u.user_id "
                "FROM qseal_users AS u "
                "WHERE EXISTS ("
                "SELECT 1 FROM qseal_orders AS o WHERE o.user_id = u.user_id"
                ")"
            ),
        },
        {
            "id": "pushdown",
            "description": "Push a selective predicate into a simple subquery source.",
            "setup_sql": _orders_setup(orders, scale_rows),
            "original_sql": (
                "SELECT order_id, amount_cents "
                "FROM (SELECT order_id, amount_cents FROM qseal_orders) AS projected_orders "
                "WHERE amount_cents > 9900"
            ),
            "rewritten_sql": (
                "SELECT order_id, amount_cents "
                "FROM ("
                "SELECT order_id, amount_cents "
                "FROM qseal_orders "
                "WHERE amount_cents > 9900"
                ") AS projected_orders"
            ),
        },
    )


def _users_setup(rows: int) -> str:
    return (
        "CREATE OR REPLACE TEMPORARY TABLE qseal_users AS\n"
        "SELECT\n"
        "  SEQ4() + 1 AS user_id,\n"
        "  IFF(MOD(SEQ4(), 5) = 0, 'active', 'inactive') AS status\n"
        f"FROM TABLE(GENERATOR(ROWCOUNT => {rows}));"
    )


def _users_id_setup(rows: int) -> str:
    return (
        "CREATE OR REPLACE TEMPORARY TABLE qseal_users AS\n"
        "SELECT SEQ4() + 1 AS user_id\n"
        f"FROM TABLE(GENERATOR(ROWCOUNT => {rows}));"
    )


def _profiles_setup(rows: int) -> str:
    return (
        "CREATE OR REPLACE TEMPORARY TABLE qseal_profiles AS\n"
        "SELECT\n"
        "  SEQ4() + 1 AS user_id,\n"
        "  'segment-' || MOD(SEQ4(), 10) AS segment\n"
        f"FROM TABLE(GENERATOR(ROWCOUNT => {rows}));"
    )


def _orders_setup(rows: int, user_rows: int) -> str:
    return (
        "CREATE OR REPLACE TEMPORARY TABLE qseal_orders AS\n"
        "SELECT\n"
        "  SEQ4() + 1 AS order_id,\n"
        f"  MOD(SEQ4(), {user_rows}) + 1 AS user_id,\n"
        "  MOD(SEQ4(), 10000) AS amount_cents\n"
        f"FROM TABLE(GENERATOR(ROWCOUNT => {rows}));"
    )


def _shape_query(
    base_sql: str,
    *,
    mode: SnowflakeFamilyMode,
    materialized_limit: int,
) -> str:
    if mode == "aggregate":
        return f"SELECT COUNT(*) AS row_count FROM ({base_sql}) AS qseal_case"
    if mode == "materialized":
        return f"SELECT * FROM ({base_sql}) AS qseal_case LIMIT {materialized_limit}"
    raise ValueError(f"Unsupported Snowflake family suite mode: {mode}")


def _classify_result(
    benchmark: BenchmarkResult,
    *,
    original_execution_ms: float | None,
    rewritten_execution_ms: float | None,
    execution_speedup: float | None,
    original_bytes: int,
    rewritten_bytes: int,
) -> str:
    if benchmark.status != BenchmarkStatus.COMPLETED:
        return "error"
    if benchmark.row_counts_match is False:
        return "row_count_mismatch"
    if not benchmark.timing_confident:
        return "low_confidence"
    if _tiny_metadata_case(
        original_execution_ms,
        rewritten_execution_ms,
        original_bytes=original_bytes,
        rewritten_bytes=rewritten_bytes,
    ):
        return "neutral_noisy"
    if benchmark.speedup is None:
        return "unknown"
    if (
        execution_speedup is not None
        and _directions_disagree(benchmark.speedup, execution_speedup)
        and _near_neutral(benchmark.speedup, tolerance=0.15)
        and _near_neutral(execution_speedup, tolerance=0.15)
    ):
        return "neutral_noisy"
    if execution_speedup is not None and 0.95 <= execution_speedup <= 1.05:
        return "neutral"
    if 0.95 <= benchmark.speedup <= 1.05:
        return "neutral"
    if benchmark.speedup >= 1.05:
        if execution_speedup is None or execution_speedup >= 1.05:
            return "positive"
        return "mixed"
    if benchmark.speedup <= 0.95:
        if execution_speedup is None or execution_speedup <= 0.95:
            return "negative"
        return "mixed"
    return "unknown"


def _case_notes(
    spec: SnowflakeFamilyCaseSpec,
    benchmark: BenchmarkResult,
    *,
    classification: str,
    original_execution_ms: float | None,
    rewritten_execution_ms: float | None,
    original_bytes: int,
    rewritten_bytes: int,
) -> tuple[str, ...]:
    notes = []
    if benchmark.status != BenchmarkStatus.COMPLETED:
        notes.append("Benchmark did not complete.")
    if spec.mode == "aggregate" and original_bytes > 0 and rewritten_bytes == 0:
        notes.append(
            "Rewritten aggregate appears metadata-answerable; treat this as "
            "aggregate-query evidence, not a full-result materialization result."
        )
    if classification == "neutral_noisy":
        if _tiny_metadata_case(
            original_execution_ms,
            rewritten_execution_ms,
            original_bytes=original_bytes,
            rewritten_bytes=rewritten_bytes,
        ):
            notes.append(
                "Snowflake execution medians and bytes scanned are too small to treat "
                "the wall-clock direction as durable evidence."
            )
        else:
            notes.append(
                "Wall-clock and Snowflake query-history execution medians disagree "
                "near the threshold; treat this as no durable direction."
            )
    if classification == "mixed":
        notes.append(
            "Wall-clock and Snowflake query-history execution medians disagree."
        )
    if (
        classification == "neutral"
        and benchmark.speedup is not None
        and not 0.95 <= benchmark.speedup <= 1.05
    ):
        notes.append(
            "Wall-clock timing crossed the threshold, but Snowflake query-history "
            "execution medians are neutral."
        )
    if _tiny_metadata_case(
        original_execution_ms,
        rewritten_execution_ms,
        original_bytes=original_bytes,
        rewritten_bytes=rewritten_bytes,
    ):
        notes.append("Both sides look metadata-only or near-metadata-only.")
    return tuple(notes)


def _tiny_metadata_case(
    original_execution_ms: float | None,
    rewritten_execution_ms: float | None,
    *,
    original_bytes: int,
    rewritten_bytes: int,
) -> bool:
    medians = [
        value
        for value in (original_execution_ms, rewritten_execution_ms)
        if value is not None
    ]
    return bool(medians) and max(medians) < 20 and original_bytes == 0 and rewritten_bytes == 0


def _directions_disagree(first_speedup: float, second_speedup: float) -> bool:
    return (first_speedup > 1.05 and second_speedup < 0.95) or (
        first_speedup < 0.95 and second_speedup > 1.05
    )


def _near_neutral(speedup: float, *, tolerance: float) -> bool:
    return (1 - tolerance) <= speedup <= (1 + tolerance)


def _plan_counts(benchmark: BenchmarkResult) -> dict[str, dict[str, int]]:
    return {
        token: {
            "original": (benchmark.original.explain or "").count(token),
            "rewritten": (benchmark.rewritten.explain or "").count(token),
        }
        for token in ("Aggregate", "Join", "Filter", "TableScan")
    }


def _classification_counts(
    summaries: Sequence[SnowflakeFamilyCaseSummary],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for summary in summaries:
        counts[summary.classification] = counts.get(summary.classification, 0) + 1
    return dict(sorted(counts.items()))


def _median(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


def _speedup(original: float | None, rewritten: float | None) -> float | None:
    if original is None or rewritten is None or rewritten <= 0:
        return None
    return original / rewritten


def _case_dir(
    output_dir: Path,
    spec: SnowflakeFamilyCaseSpec,
    run_index: int,
) -> Path:
    return (
        output_dir
        / f"run-{run_index:03d}"
        / _scale_slug(spec.scale_rows)
        / spec.mode
        / spec.rewrite_family
    )


def _scale_slug(rows: int) -> str:
    if rows >= 1_000_000 and rows % 1_000_000 == 0:
        return f"{rows // 1_000_000}m"
    if rows >= 1_000 and rows % 1_000 == 0:
        return f"{rows // 1_000}k"
    return f"{rows}_rows"


def _validate_case_settings(
    scales: Sequence[int],
    modes: Sequence[SnowflakeFamilyMode],
    materialized_limit: int,
) -> None:
    if not scales:
        raise ValueError("At least one scale is required.")
    if not modes:
        raise ValueError("At least one mode is required.")
    if materialized_limit < 1:
        raise ValueError("materialized_limit must be one or greater.")
    for scale in scales:
        if scale < 1:
            raise ValueError("scale rows must be one or greater.")
    for mode in modes:
        if mode not in ("aggregate", "materialized"):
            raise ValueError(f"Unsupported Snowflake family suite mode: {mode}")


def _benchmark_json(result: BenchmarkResult) -> str:
    payload: dict[str, Any] = result.model_dump(mode="json")
    payload["schema_version"] = 1
    payload["artifact_type"] = "snowflake_benchmark"
    payload["dialect"] = "snowflake"
    return json.dumps(payload, indent=2, sort_keys=True)
