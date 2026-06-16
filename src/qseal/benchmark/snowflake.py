from __future__ import annotations

import importlib
import os
import platform
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from math import ceil
from typing import Any

from sqlglot import exp, parse_one
from sqlglot.errors import ParseError

from qseal.benchmark.model import (
    BenchmarkEnvironment,
    BenchmarkResult,
    BenchmarkStatus,
    QueryBenchmark,
)


class SnowflakeConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class SnowflakeConnectionConfig:
    account: str
    user: str
    password: str
    warehouse: str
    database: str
    schema: str
    role: str | None = None
    query_tag: str = "qseal-tier3"

    @classmethod
    def from_env(cls, *, query_tag: str | None = None) -> SnowflakeConnectionConfig:
        values = {
            "account": os.environ.get("QSEAL_SNOWFLAKE_ACCOUNT", ""),
            "user": os.environ.get("QSEAL_SNOWFLAKE_USER", ""),
            "password": os.environ.get("QSEAL_SNOWFLAKE_PASSWORD", ""),
            "warehouse": os.environ.get("QSEAL_SNOWFLAKE_WAREHOUSE", ""),
            "database": os.environ.get("QSEAL_SNOWFLAKE_DATABASE", ""),
            "schema": os.environ.get("QSEAL_SNOWFLAKE_SCHEMA", ""),
            "role": os.environ.get("QSEAL_SNOWFLAKE_ROLE") or None,
            "query_tag": query_tag
            or os.environ.get("QSEAL_SNOWFLAKE_QUERY_TAG")
            or "qseal-tier3",
        }
        missing = [
            name
            for name in (
                "account",
                "user",
                "password",
                "warehouse",
                "database",
                "schema",
            )
            if not values[name]
        ]
        if missing:
            names = ", ".join(f"QSEAL_SNOWFLAKE_{name.upper()}" for name in missing)
            raise SnowflakeConfigurationError(
                f"Missing required Snowflake environment variables: {names}."
            )
        return cls(**values)

    def connect_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "account": self.account,
            "user": self.user,
            "password": self.password,
            "warehouse": self.warehouse,
            "database": self.database,
            "schema": self.schema,
            "session_parameters": {
                "QUERY_TAG": self.query_tag,
            },
        }
        if self.role:
            kwargs["role"] = self.role
        return kwargs


ConnectorFactory = Callable[[SnowflakeConnectionConfig], Any]


def benchmark_query_pair(
    original_sql: str,
    rewritten_sql: str,
    *,
    setup_sql: str | None = None,
    warmups: int = 2,
    repetitions: int = 5,
    timeout_seconds: float = 30.0,
    minimum_duration_ms: float = 0.0,
    query_tag: str | None = None,
    config: SnowflakeConnectionConfig | None = None,
    connector_factory: ConnectorFactory | None = None,
) -> BenchmarkResult:
    _validate_settings(warmups, repetitions, timeout_seconds, minimum_duration_ms)
    try:
        config = config or SnowflakeConnectionConfig.from_env(query_tag=query_tag)
    except SnowflakeConfigurationError as error:
        environment = _failed_environment(
            warmups=warmups,
            repetitions=repetitions,
            timeout_seconds=timeout_seconds,
            minimum_duration_ms=minimum_duration_ms,
        )
        return _failed_result(
            original_sql,
            rewritten_sql,
            environment,
            BenchmarkStatus.ERROR,
            str(error),
        )
    if query_tag is not None:
        config = replace(config, query_tag=query_tag)
    environment = _environment(
        config,
        warmups=warmups,
        repetitions=repetitions,
        timeout_seconds=timeout_seconds,
        minimum_duration_ms=minimum_duration_ms,
    )
    connector_factory = connector_factory or _default_connector_factory
    connection = None
    try:
        _validate_select_query(original_sql, label="original")
        _validate_select_query(rewritten_sql, label="rewritten")
        connection = connector_factory(config)
        _configure_session(connection, config, timeout_seconds)
        if setup_sql:
            _execute_setup(connection, setup_sql)

        for index in range(warmups):
            queries = (
                (original_sql, rewritten_sql)
                if index % 2 == 0
                else (rewritten_sql, original_sql)
            )
            for sql in queries:
                _execute_query(connection, sql)

        plans = {
            "original": _explain(connection, original_sql),
            "rewritten": _explain(connection, rewritten_sql),
        }
        samples: dict[str, list[float]] = {"original": [], "rewritten": []}
        row_counts: dict[str, int] = {}
        query_ids: dict[str, list[str]] = {"original": [], "rewritten": []}
        metadata: dict[str, list[dict[str, Any]]] = {"original": [], "rewritten": []}
        for index in range(repetitions):
            labels = (
                ("original", "rewritten")
                if index % 2 == 0
                else ("rewritten", "original")
            )
            for label in labels:
                sql = original_sql if label == "original" else rewritten_sql
                sample = _execute_query(connection, sql)
                samples[label].append(sample.elapsed_ms)
                row_counts[label] = sample.row_count
                if sample.query_id:
                    query_ids[label].append(sample.query_id)
                    metadata[label].append(_query_history(connection, sample.query_id))

        original = _completed_query(
            original_sql,
            samples["original"],
            query_ids["original"],
            row_counts["original"],
            plans["original"],
            metadata["original"],
        )
        rewritten = _completed_query(
            rewritten_sql,
            samples["rewritten"],
            query_ids["rewritten"],
            row_counts["rewritten"],
            plans["rewritten"],
            metadata["rewritten"],
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
    except SnowflakeConfigurationError as error:
        return _failed_result(
            original_sql,
            rewritten_sql,
            environment,
            BenchmarkStatus.ERROR,
            str(error),
        )
    except Exception as error:
        status = BenchmarkStatus.TIMEOUT if _looks_like_timeout(error) else BenchmarkStatus.ERROR
        return _failed_result(
            original_sql,
            rewritten_sql,
            environment,
            status,
            str(error),
        )
    finally:
        if connection is not None:
            connection.close()


@dataclass(frozen=True)
class _QuerySample:
    elapsed_ms: float
    row_count: int
    query_id: str | None


def _default_connector_factory(config: SnowflakeConnectionConfig) -> Any:
    try:
        connector = importlib.import_module("snowflake.connector")
    except ImportError as error:
        raise SnowflakeConfigurationError(
            "Snowflake benchmarking requires the snowflake-connector-python package."
        ) from error
    return connector.connect(**config.connect_kwargs())


def _environment(
    config: SnowflakeConnectionConfig,
    *,
    warmups: int,
    repetitions: int,
    timeout_seconds: float,
    minimum_duration_ms: float,
) -> BenchmarkEnvironment:
    return BenchmarkEnvironment(
        engine="snowflake",
        snowflake_connector_version=_snowflake_connector_version(),
        snowflake_account=config.account,
        snowflake_user=config.user,
        snowflake_role=config.role,
        snowflake_warehouse=config.warehouse,
        snowflake_database=config.database,
        snowflake_schema=config.schema,
        snowflake_query_tag=config.query_tag,
        python_version=platform.python_version(),
        platform=platform.platform(),
        database_path=f"{config.database}.{config.schema}",
        threads=1,
        warmups=warmups,
        repetitions=repetitions,
        timeout_seconds=timeout_seconds,
        minimum_duration_ms=minimum_duration_ms,
    )


def _failed_environment(
    *,
    warmups: int,
    repetitions: int,
    timeout_seconds: float,
    minimum_duration_ms: float,
) -> BenchmarkEnvironment:
    return BenchmarkEnvironment(
        engine="snowflake",
        snowflake_connector_version=_snowflake_connector_version(),
        python_version=platform.python_version(),
        platform=platform.platform(),
        database_path="",
        threads=1,
        warmups=warmups,
        repetitions=repetitions,
        timeout_seconds=timeout_seconds,
        minimum_duration_ms=minimum_duration_ms,
    )


def _snowflake_connector_version() -> str | None:
    try:
        connector = importlib.import_module("snowflake.connector")
    except ImportError:
        return None
    return getattr(connector, "__version__", None)


def _configure_session(
    connection: Any,
    config: SnowflakeConnectionConfig,
    timeout_seconds: float,
) -> None:
    timeout = max(1, ceil(timeout_seconds))
    with connection.cursor() as cursor:
        cursor.execute(f"USE WAREHOUSE {_quote_identifier(config.warehouse)}")
        cursor.execute(f"USE DATABASE {_quote_identifier(config.database)}")
        cursor.execute(f"USE SCHEMA {_quote_identifier(config.schema)}")
        cursor.execute(f"ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = {timeout}")
        cursor.execute("ALTER SESSION SET USE_CACHED_RESULT = FALSE")
        cursor.execute(
            "ALTER SESSION SET QUERY_TAG = "
            f"{_quote_string(config.query_tag)}"
        )


def _execute_setup(connection: Any, setup_sql: str) -> None:
    if hasattr(connection, "execute_string"):
        connection.execute_string(setup_sql)
        return
    with connection.cursor() as cursor:
        cursor.execute(setup_sql)


def _execute_query(connection: Any, sql: str) -> _QuerySample:
    started = time.perf_counter_ns()
    with connection.cursor() as cursor:
        cursor.execute(sql)
        rows = cursor.fetchall()
        query_id = getattr(cursor, "sfqid", None)
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    return _QuerySample(
        elapsed_ms=elapsed_ms,
        row_count=len(rows),
        query_id=query_id,
    )


def _explain(connection: Any, sql: str) -> str | None:
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"EXPLAIN USING TEXT {sql}")
            rows = cursor.fetchall()
    except Exception:
        return None
    return "\n".join(" ".join(str(value) for value in row) for row in rows)


def _query_history(connection: Any, query_id: str) -> dict[str, Any]:
    sql = """
        SELECT
          QUERY_ID,
          BYTES_SCANNED,
          COMPILATION_TIME,
          EXECUTION_TIME,
          TOTAL_ELAPSED_TIME,
          ROWS_PRODUCED
        FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY_BY_SESSION(RESULT_LIMIT => 100))
        WHERE QUERY_ID = %s
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, (query_id,))
            row = cursor.fetchone()
    except Exception:
        return {}
    if row is None:
        return {}
    return {
        "query_id": row[0],
        "bytes_scanned": row[1],
        "compilation_time_ms": row[2],
        "execution_time_ms": row[3],
        "total_elapsed_time_ms": row[4],
        "rows_produced": row[5],
    }


def _completed_query(
    sql: str,
    timings_ms: list[float],
    query_ids: list[str],
    row_count: int,
    explain: str | None,
    metadata: list[dict[str, Any]],
) -> QueryBenchmark:
    median_ms = statistics.median(timings_ms)
    deviations = [abs(timing - median_ms) for timing in timings_ms]
    return QueryBenchmark(
        status=BenchmarkStatus.COMPLETED,
        sql=sql.strip(),
        query_ids=tuple(query_ids),
        timings_ms=tuple(timings_ms),
        batch_timings_ms=tuple(timings_ms),
        executions_per_sample=1,
        median_ms=median_ms,
        median_absolute_deviation_ms=statistics.median(deviations),
        min_ms=min(timings_ms),
        max_ms=max(timings_ms),
        row_count=row_count,
        explain=explain,
        bytes_scanned=_metadata_tuple(metadata, "bytes_scanned", int),
        compilation_time_ms=_metadata_tuple(metadata, "compilation_time_ms", float),
        execution_time_ms=_metadata_tuple(metadata, "execution_time_ms", float),
        total_elapsed_time_ms=_metadata_tuple(metadata, "total_elapsed_time_ms", float),
    )


def _metadata_tuple(
    metadata: list[dict[str, Any]],
    key: str,
    cast: Callable[[Any], Any],
) -> tuple[Any, ...]:
    values = []
    for item in metadata:
        value = item.get(key)
        if value is not None:
            values.append(cast(value))
    return tuple(values)


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


def _validate_select_query(sql: str, *, label: str) -> None:
    try:
        expression = parse_one(sql, read="snowflake")
    except ParseError as error:
        raise SnowflakeConfigurationError(
            f"{label} query must be a parseable SELECT statement."
        ) from error
    if not isinstance(expression, exp.Query):
        raise SnowflakeConfigurationError(f"{label} query must be SELECT-only.")


def _validate_settings(
    warmups: int,
    repetitions: int,
    timeout_seconds: float,
    minimum_duration_ms: float,
) -> None:
    if warmups < 0:
        raise ValueError("warmups must be zero or greater.")
    if repetitions < 1:
        raise ValueError("repetitions must be one or greater.")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero.")
    if minimum_duration_ms < 0:
        raise ValueError("minimum_duration_ms must be zero or greater.")


def _timing_target_reached(
    benchmark: QueryBenchmark,
    minimum_duration_ms: float,
) -> bool:
    if minimum_duration_ms <= 0:
        return True
    if not benchmark.batch_timings_ms:
        return False
    return statistics.median(benchmark.batch_timings_ms) >= minimum_duration_ms


def _confidence_reason(
    timing_confident: bool,
    minimum_duration_ms: float,
) -> str | None:
    if timing_confident:
        return None
    return (
        "The median Snowflake sample duration did not reach the "
        f"{minimum_duration_ms:g} ms minimum sample duration."
    )


def _looks_like_timeout(error: Exception) -> bool:
    text = str(error).lower()
    return "timeout" in text or "statement_timeout" in text or "timed out" in text


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _quote_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
