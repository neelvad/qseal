from __future__ import annotations

import platform
import statistics
import threading
import time
from pathlib import Path

import duckdb

from snowprove.benchmark.model import (
    BenchmarkEnvironment,
    BenchmarkResult,
    BenchmarkStatus,
    QueryBenchmark,
)


class QueryTimedOutError(RuntimeError):
    pass


def benchmark_query_pair(
    original_sql: str,
    rewritten_sql: str,
    *,
    database_path: Path | str = ":memory:",
    setup_sql: str | None = None,
    warmups: int = 2,
    repetitions: int = 5,
    timeout_seconds: float = 30.0,
    threads: int = 1,
) -> BenchmarkResult:
    _validate_settings(warmups, repetitions, timeout_seconds, threads)
    database = str(database_path)
    environment = BenchmarkEnvironment(
        duckdb_version=duckdb.__version__,
        python_version=platform.python_version(),
        platform=platform.platform(),
        database_path=database,
        threads=threads,
        warmups=warmups,
        repetitions=repetitions,
        timeout_seconds=timeout_seconds,
    )

    connection = duckdb.connect(database)
    try:
        connection.execute(f"SET threads = {threads}")
        if setup_sql:
            connection.execute(setup_sql)

        original_plan = _explain(connection, original_sql, timeout_seconds)
        rewritten_plan = _explain(connection, rewritten_sql, timeout_seconds)

        for index in range(warmups):
            queries = (
                (original_sql, rewritten_sql)
                if index % 2 == 0
                else (rewritten_sql, original_sql)
            )
            for sql in queries:
                _execute_timed(connection, sql, timeout_seconds)

        samples: dict[str, list[float]] = {"original": [], "rewritten": []}
        row_counts: dict[str, int] = {}
        for index in range(repetitions):
            labels = ("original", "rewritten") if index % 2 == 0 else ("rewritten", "original")
            for label in labels:
                sql = original_sql if label == "original" else rewritten_sql
                elapsed_ms, row_count = _execute_timed(connection, sql, timeout_seconds)
                samples[label].append(elapsed_ms)
                row_counts[label] = row_count

        original = _completed_query(
            original_sql,
            samples["original"],
            row_counts["original"],
            original_plan,
        )
        rewritten = _completed_query(
            rewritten_sql,
            samples["rewritten"],
            row_counts["rewritten"],
            rewritten_plan,
        )
        speedup = (
            original.median_ms / rewritten.median_ms
            if original.median_ms is not None
            and rewritten.median_ms is not None
            and rewritten.median_ms > 0
            else None
        )
        return BenchmarkResult(
            status=BenchmarkStatus.COMPLETED,
            original=original,
            rewritten=rewritten,
            environment=environment,
            speedup=speedup,
            row_counts_match=original.row_count == rewritten.row_count,
        )
    except QueryTimedOutError as error:
        return _failed_result(
            original_sql,
            rewritten_sql,
            environment,
            BenchmarkStatus.TIMEOUT,
            str(error),
        )
    except duckdb.Error as error:
        return _failed_result(
            original_sql,
            rewritten_sql,
            environment,
            BenchmarkStatus.ERROR,
            str(error),
        )
    finally:
        connection.close()


def _execute_timed(
    connection: duckdb.DuckDBPyConnection,
    sql: str,
    timeout_seconds: float,
) -> tuple[float, int]:
    started = time.perf_counter_ns()
    rows = _execute_with_timeout(connection, sql, timeout_seconds)
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    return elapsed_ms, len(rows)


def _execute_with_timeout(
    connection: duckdb.DuckDBPyConnection,
    sql: str,
    timeout_seconds: float,
) -> list[tuple[object, ...]]:
    finished = threading.Event()
    timed_out = threading.Event()

    def interrupt_after_timeout() -> None:
        if not finished.wait(timeout_seconds):
            timed_out.set()
            connection.interrupt()

    watchdog = threading.Thread(target=interrupt_after_timeout, daemon=True)
    watchdog.start()
    try:
        rows = connection.execute(sql).fetchall()
    except duckdb.Error as error:
        if timed_out.is_set():
            raise QueryTimedOutError(
                f"Query exceeded the {timeout_seconds:g} second timeout."
            ) from error
        raise
    finally:
        finished.set()
        watchdog.join()

    if timed_out.is_set():
        raise QueryTimedOutError(f"Query exceeded the {timeout_seconds:g} second timeout.")
    return rows


def _explain(
    connection: duckdb.DuckDBPyConnection,
    sql: str,
    timeout_seconds: float,
) -> str:
    rows = _execute_with_timeout(connection, f"EXPLAIN {sql}", timeout_seconds)
    return "\n".join(str(row[-1]) for row in rows)


def _completed_query(
    sql: str,
    timings_ms: list[float],
    row_count: int,
    explain: str,
) -> QueryBenchmark:
    median_ms = statistics.median(timings_ms)
    deviations = [abs(timing - median_ms) for timing in timings_ms]
    return QueryBenchmark(
        status=BenchmarkStatus.COMPLETED,
        sql=sql.strip(),
        timings_ms=tuple(timings_ms),
        median_ms=median_ms,
        median_absolute_deviation_ms=statistics.median(deviations),
        min_ms=min(timings_ms),
        max_ms=max(timings_ms),
        row_count=row_count,
        explain=explain,
    )


def _failed_result(
    original_sql: str,
    rewritten_sql: str,
    environment: BenchmarkEnvironment,
    status: BenchmarkStatus,
    reason: str,
) -> BenchmarkResult:
    return BenchmarkResult(
        status=status,
        original=QueryBenchmark(status=status, sql=original_sql.strip(), error=reason),
        rewritten=QueryBenchmark(status=status, sql=rewritten_sql.strip(), error=reason),
        environment=environment,
        reason=reason,
    )


def _validate_settings(
    warmups: int,
    repetitions: int,
    timeout_seconds: float,
    threads: int,
) -> None:
    if warmups < 0:
        raise ValueError("warmups must be zero or greater.")
    if repetitions < 1:
        raise ValueError("repetitions must be one or greater.")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero.")
    if threads < 1:
        raise ValueError("threads must be one or greater.")
