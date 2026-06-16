import pytest

from qseal.benchmark.model import BenchmarkStatus
from qseal.benchmark.snowflake import (
    SnowflakeConnectionConfig,
    benchmark_query_pair,
)


def test_benchmarks_snowflake_query_pair_with_query_metadata() -> None:
    connection = _FakeConnection()
    result = benchmark_query_pair(
        "SELECT DISTINCT user_id FROM users",
        "SELECT user_id FROM users",
        setup_sql="CREATE TEMP TABLE users AS SELECT 1 AS user_id",
        warmups=1,
        repetitions=2,
        timeout_seconds=5,
        query_tag="qseal-test",
        config=_config(),
        connector_factory=lambda _config: connection,
    )

    assert result.status == BenchmarkStatus.COMPLETED
    assert result.environment.engine == "snowflake"
    assert result.environment.snowflake_account == "acct"
    assert result.environment.snowflake_warehouse == "QSEAL_WH"
    assert result.environment.snowflake_query_tag == "qseal-test"
    assert result.original.row_count == 2
    assert result.rewritten.row_count == 2
    assert result.row_counts_match is True
    assert result.speedup is not None
    assert len(result.original.timings_ms) == 2
    assert len(result.rewritten.timings_ms) == 2
    assert len(result.original.query_ids) == 2
    assert len(result.rewritten.query_ids) == 2
    assert result.original.bytes_scanned
    assert result.rewritten.execution_time_ms
    assert result.original.explain == "plan"
    assert connection.setup_sql == "CREATE TEMP TABLE users AS SELECT 1 AS user_id"
    assert any("USE WAREHOUSE" in statement for statement in connection.statements)
    assert any("USE_CACHED_RESULT = FALSE" in statement for statement in connection.statements)


def test_reports_missing_snowflake_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "QSEAL_SNOWFLAKE_ACCOUNT",
        "QSEAL_SNOWFLAKE_USER",
        "QSEAL_SNOWFLAKE_PASSWORD",
        "QSEAL_SNOWFLAKE_WAREHOUSE",
        "QSEAL_SNOWFLAKE_DATABASE",
        "QSEAL_SNOWFLAKE_SCHEMA",
    ):
        monkeypatch.delenv(name, raising=False)

    result = benchmark_query_pair(
        "SELECT 1",
        "SELECT 1",
        warmups=0,
        repetitions=1,
    )

    assert result.status == BenchmarkStatus.ERROR
    assert "QSEAL_SNOWFLAKE_ACCOUNT" in str(result.reason)
    assert result.environment.engine == "snowflake"


def test_rejects_non_select_snowflake_benchmark_queries() -> None:
    result = benchmark_query_pair(
        "DROP TABLE users",
        "SELECT 1",
        warmups=0,
        repetitions=1,
        config=_config(),
        connector_factory=lambda _config: _FakeConnection(),
    )

    assert result.status == BenchmarkStatus.ERROR
    assert "SELECT-only" in str(result.reason)


def test_marks_snowflake_timeout_errors() -> None:
    result = benchmark_query_pair(
        "SELECT 1",
        "SELECT 1",
        warmups=0,
        repetitions=1,
        config=_config(),
        connector_factory=lambda _config: _TimeoutConnection(),
    )

    assert result.status == BenchmarkStatus.TIMEOUT
    assert "timeout" in str(result.reason).lower()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"warmups": -1}, "warmups"),
        ({"repetitions": 0}, "repetitions"),
        ({"timeout_seconds": 0}, "timeout_seconds"),
        ({"minimum_duration_ms": -1}, "minimum_duration_ms"),
    ],
)
def test_rejects_invalid_snowflake_benchmark_settings(kwargs, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        benchmark_query_pair("SELECT 1", "SELECT 1", config=_config(), **kwargs)


def _config() -> SnowflakeConnectionConfig:
    return SnowflakeConnectionConfig(
        account="acct",
        user="user",
        password="secret",
        warehouse="QSEAL_WH",
        database="QSEAL_DEV",
        schema="BENCHMARKS",
    )


class _FakeConnection:
    def __init__(self) -> None:
        self.statements = []
        self.setup_sql = None
        self.closed = False
        self._counter = 0

    def cursor(self):
        return _FakeCursor(self)

    def execute_string(self, sql: str) -> None:
        self.setup_sql = sql

    def close(self) -> None:
        self.closed = True


class _TimeoutConnection(_FakeConnection):
    def cursor(self):
        return _TimeoutCursor(self)


class _FakeCursor:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection
        self.sfqid = None
        self._rows = []
        self._one = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def execute(self, sql: str, params=None):
        self.connection.statements.append(sql)
        normalized = " ".join(sql.split()).upper()
        if normalized.startswith("EXPLAIN"):
            self.sfqid = None
            self._rows = [("plan",)]
            return self
        if "QUERY_HISTORY_BY_SESSION" in normalized:
            query_id = params[0]
            self.sfqid = None
            self._one = (query_id, 100, 2.0, 3.0, 5.0, 2)
            return self
        if normalized.startswith(("USE ", "ALTER SESSION")):
            self.sfqid = None
            self._rows = []
            return self
        self.connection._counter += 1
        self.sfqid = f"q-{self.connection._counter}"
        self._rows = [(1,), (2,)]
        return self

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._one


class _TimeoutCursor(_FakeCursor):
    def execute(self, sql: str, params=None):
        normalized = " ".join(sql.split()).upper()
        if normalized.startswith(("USE ", "ALTER SESSION")):
            return super().execute(sql, params)
        raise RuntimeError("statement timeout")
