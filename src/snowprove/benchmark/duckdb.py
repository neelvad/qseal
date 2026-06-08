from __future__ import annotations

import platform
import statistics
import threading
import time
from math import ceil
from pathlib import Path

import duckdb

from snowprove.benchmark.model import (
    BenchmarkEnvironment,
    BenchmarkResult,
    BenchmarkStatus,
    QueryBenchmark,
    QueryBenchmarkResult,
)


class QueryTimedOutError(RuntimeError):
    pass


_MAX_EXECUTIONS_PER_SAMPLE = 1_000


def benchmark_query(
    sql: str,
    *,
    database_path: Path | str = ":memory:",
    setup_sql: str | None = None,
    warmups: int = 2,
    repetitions: int = 5,
    timeout_seconds: float = 30.0,
    threads: int = 1,
    minimum_duration_ms: float = 0.0,
) -> QueryBenchmarkResult:
    _validate_settings(
        warmups,
        repetitions,
        timeout_seconds,
        threads,
        minimum_duration_ms,
    )
    environment = _environment(
        database_path,
        threads=threads,
        warmups=warmups,
        repetitions=repetitions,
        timeout_seconds=timeout_seconds,
        minimum_duration_ms=minimum_duration_ms,
    )
    connection = duckdb.connect(str(database_path))
    try:
        connection.execute(f"SET threads = {threads}")
        if setup_sql:
            connection.execute(setup_sql)
        query = _benchmark_query_on_connection(
            connection,
            sql,
            warmups=warmups,
            repetitions=repetitions,
            timeout_seconds=timeout_seconds,
            minimum_duration_ms=minimum_duration_ms,
        )
        timing_confident = _timing_target_reached(query, minimum_duration_ms)
        return QueryBenchmarkResult(
            status=BenchmarkStatus.COMPLETED,
            query=query,
            environment=environment,
            timing_confident=timing_confident,
            confidence_reason=_confidence_reason(timing_confident, minimum_duration_ms),
        )
    except QueryTimedOutError as error:
        return _failed_query_result(sql, environment, BenchmarkStatus.TIMEOUT, str(error))
    except duckdb.Error as error:
        return _failed_query_result(sql, environment, BenchmarkStatus.ERROR, str(error))
    finally:
        connection.close()


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
    minimum_duration_ms: float = 0.0,
) -> BenchmarkResult:
    _validate_settings(
        warmups,
        repetitions,
        timeout_seconds,
        threads,
        minimum_duration_ms,
    )
    environment = _environment(
        database_path,
        threads=threads,
        warmups=warmups,
        repetitions=repetitions,
        timeout_seconds=timeout_seconds,
        minimum_duration_ms=minimum_duration_ms,
    )

    connection = duckdb.connect(str(database_path))
    try:
        connection.execute(f"SET threads = {threads}")
        if setup_sql:
            connection.execute(setup_sql)

        for index in range(warmups):
            queries = (
                (original_sql, rewritten_sql)
                if index % 2 == 0
                else (rewritten_sql, original_sql)
            )
            for sql in queries:
                _execute_timed(connection, sql, timeout_seconds)

        plans = {
            "original": _explain(connection, original_sql, timeout_seconds),
            "rewritten": _explain(connection, rewritten_sql, timeout_seconds),
        }
        executions_per_sample = {
            "original": _calibrate_executions_per_sample(
                connection,
                original_sql,
                timeout_seconds,
                minimum_duration_ms,
            ),
            "rewritten": _calibrate_executions_per_sample(
                connection,
                rewritten_sql,
                timeout_seconds,
                minimum_duration_ms,
            ),
        }
        samples: dict[str, list[float]] = {"original": [], "rewritten": []}
        batch_samples: dict[str, list[float]] = {"original": [], "rewritten": []}
        row_counts: dict[str, int] = {}
        for index in range(repetitions):
            labels = (
                ("original", "rewritten")
                if index % 2 == 0
                else ("rewritten", "original")
            )
            for label in labels:
                sql = original_sql if label == "original" else rewritten_sql
                batch_elapsed_ms, row_count = _execute_timed_batch(
                    connection,
                    sql,
                    timeout_seconds,
                    executions_per_sample[label],
                )
                batch_samples[label].append(batch_elapsed_ms)
                samples[label].append(
                    batch_elapsed_ms / executions_per_sample[label]
                )
                row_counts[label] = row_count

        original = _completed_query(
            original_sql,
            samples["original"],
            batch_samples["original"],
            executions_per_sample["original"],
            row_counts["original"],
            plans["original"],
        )
        rewritten = _completed_query(
            rewritten_sql,
            samples["rewritten"],
            batch_samples["rewritten"],
            executions_per_sample["rewritten"],
            row_counts["rewritten"],
            plans["rewritten"],
        )
        speedup = (
            original.median_ms / rewritten.median_ms
            if original.median_ms is not None
            and rewritten.median_ms is not None
            and rewritten.median_ms > 0
            else None
        )
        timing_confident = all(
            _timing_target_reached(query, minimum_duration_ms)
            for query in (original, rewritten)
        )
        return BenchmarkResult(
            status=BenchmarkStatus.COMPLETED,
            original=original,
            rewritten=rewritten,
            environment=environment,
            speedup=speedup,
            row_counts_match=original.row_count == rewritten.row_count,
            timing_confident=timing_confident,
            confidence_reason=_confidence_reason(timing_confident, minimum_duration_ms),
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


def _environment(
    database_path: Path | str,
    *,
    threads: int,
    warmups: int,
    repetitions: int,
    timeout_seconds: float,
    minimum_duration_ms: float,
) -> BenchmarkEnvironment:
    return BenchmarkEnvironment(
        duckdb_version=duckdb.__version__,
        python_version=platform.python_version(),
        platform=platform.platform(),
        database_path=str(database_path),
        threads=threads,
        warmups=warmups,
        repetitions=repetitions,
        timeout_seconds=timeout_seconds,
        minimum_duration_ms=minimum_duration_ms,
    )


def _benchmark_query_on_connection(
    connection: duckdb.DuckDBPyConnection,
    sql: str,
    *,
    warmups: int,
    repetitions: int,
    timeout_seconds: float,
    minimum_duration_ms: float,
) -> QueryBenchmark:
    for _ in range(warmups):
        _execute_timed(connection, sql, timeout_seconds)
    return _completed_query(
        sql,
        *_measure_query(
            connection,
            sql,
            repetitions,
            timeout_seconds,
            minimum_duration_ms,
        ),
    )


def _measure_query(
    connection: duckdb.DuckDBPyConnection,
    sql: str,
    repetitions: int,
    timeout_seconds: float,
    minimum_duration_ms: float,
) -> tuple[list[float], list[float], int, int, str]:
    plan = _explain(connection, sql, timeout_seconds)
    executions_per_sample = _calibrate_executions_per_sample(
        connection,
        sql,
        timeout_seconds,
        minimum_duration_ms,
    )
    samples = []
    batch_samples = []
    row_count = 0
    for _ in range(repetitions):
        batch_elapsed_ms, row_count = _execute_timed_batch(
            connection,
            sql,
            timeout_seconds,
            executions_per_sample,
        )
        batch_samples.append(batch_elapsed_ms)
        samples.append(batch_elapsed_ms / executions_per_sample)
    return samples, batch_samples, executions_per_sample, row_count, plan


def _execute_timed(
    connection: duckdb.DuckDBPyConnection,
    sql: str,
    timeout_seconds: float,
) -> tuple[float, int]:
    started = time.perf_counter_ns()
    rows = _execute_with_timeout(connection, sql, timeout_seconds)
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    return elapsed_ms, len(rows)


def _execute_timed_batch(
    connection: duckdb.DuckDBPyConnection,
    sql: str,
    timeout_seconds: float,
    executions: int,
) -> tuple[float, int]:
    started = time.perf_counter_ns()
    row_count = 0
    for _ in range(executions):
        rows = _execute_with_timeout(connection, sql, timeout_seconds)
        row_count = len(rows)
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    return elapsed_ms, row_count


def _calibrate_executions_per_sample(
    connection: duckdb.DuckDBPyConnection,
    sql: str,
    timeout_seconds: float,
    minimum_duration_ms: float,
) -> int:
    if minimum_duration_ms <= 0:
        return 1
    elapsed_ms, _ = _execute_timed(connection, sql, timeout_seconds)
    if elapsed_ms <= 0:
        return _MAX_EXECUTIONS_PER_SAMPLE
    return min(
        _MAX_EXECUTIONS_PER_SAMPLE,
        max(1, ceil(minimum_duration_ms / elapsed_ms)),
    )


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
    batch_timings_ms: list[float],
    executions_per_sample: int,
    row_count: int,
    explain: str,
) -> QueryBenchmark:
    median_ms = statistics.median(timings_ms)
    deviations = [abs(timing - median_ms) for timing in timings_ms]
    return QueryBenchmark(
        status=BenchmarkStatus.COMPLETED,
        sql=sql.strip(),
        timings_ms=tuple(timings_ms),
        batch_timings_ms=tuple(batch_timings_ms),
        executions_per_sample=executions_per_sample,
        median_ms=median_ms,
        median_absolute_deviation_ms=statistics.median(deviations),
        min_ms=min(timings_ms),
        max_ms=max(timings_ms),
        row_count=row_count,
        explain=explain,
    )


def _timing_target_reached(
    benchmark: QueryBenchmark,
    minimum_duration_ms: float,
) -> bool:
    if minimum_duration_ms <= 0:
        return True
    if benchmark.executions_per_sample < _MAX_EXECUTIONS_PER_SAMPLE:
        return True
    return statistics.median(benchmark.batch_timings_ms) >= minimum_duration_ms


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


def _failed_query_result(
    sql: str,
    environment: BenchmarkEnvironment,
    status: BenchmarkStatus,
    reason: str,
) -> QueryBenchmarkResult:
    return QueryBenchmarkResult(
        status=status,
        query=QueryBenchmark(status=status, sql=sql.strip(), error=reason),
        environment=environment,
        reason=reason,
    )


def _confidence_reason(
    timing_confident: bool,
    minimum_duration_ms: float,
) -> str | None:
    if timing_confident:
        return None
    return (
        "The timing batch safety cap could not reach the "
        f"{minimum_duration_ms:g} ms minimum sample duration."
    )


def _validate_settings(
    warmups: int,
    repetitions: int,
    timeout_seconds: float,
    threads: int,
    minimum_duration_ms: float,
) -> None:
    if warmups < 0:
        raise ValueError("warmups must be zero or greater.")
    if repetitions < 1:
        raise ValueError("repetitions must be one or greater.")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero.")
    if threads < 1:
        raise ValueError("threads must be one or greater.")
    if minimum_duration_ms < 0:
        raise ValueError("minimum_duration_ms must be zero or greater.")
