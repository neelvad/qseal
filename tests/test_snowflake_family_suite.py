import json

from qseal.benchmark.model import (
    BenchmarkEnvironment,
    BenchmarkResult,
    BenchmarkStatus,
    QueryBenchmark,
)
from qseal.benchmark.snowflake import SnowflakeConnectionConfig
from qseal.benchmark.snowflake_suite import (
    run_snowflake_family_suite,
    snowflake_family_cases,
    summarize_snowflake_family_case,
)
from qseal.report.json import render_snowflake_family_suite_json
from qseal.report.text import render_snowflake_family_suite_report


def test_builds_snowflake_family_cases_for_modes_and_scales() -> None:
    cases = snowflake_family_cases(
        scales=(1_000,),
        modes=("aggregate", "materialized"),
        materialized_limit=25,
    )

    assert len(cases) == 10
    assert {case.rewrite_family for case in cases} == {
        "distinct",
        "not_null",
        "left_join",
        "exists",
        "pushdown",
    }
    aggregate = next(case for case in cases if case.case_id == "aggregate-1k-distinct")
    materialized = next(
        case for case in cases if case.case_id == "materialized-1k-distinct"
    )
    assert "GENERATOR(ROWCOUNT => 1000)" in aggregate.setup_sql
    assert "COUNT(*) AS row_count" in aggregate.original_sql
    assert "LIMIT 25" in materialized.original_sql
    assert materialized.evidence_scope == "bounded_materialized_output"


def test_runs_snowflake_family_suite_with_fake_connector(tmp_path) -> None:
    connections: list[_FakeConnection] = []

    def factory(_config: SnowflakeConnectionConfig) -> _FakeConnection:
        connection = _FakeConnection()
        connections.append(connection)
        return connection

    report = run_snowflake_family_suite(
        tmp_path,
        scales=(1_000,),
        modes=("aggregate",),
        runs=1,
        warmups=0,
        repetitions=1,
        config=_config(),
        connector_factory=factory,
    )

    assert report.result_count == 5
    assert report.completed_count == 5
    assert len(connections) == 5
    assert all(connection.closed for connection in connections)
    assert {summary.status for summary in report.summaries} == {
        BenchmarkStatus.COMPLETED
    }

    case_dir = tmp_path / "run-001" / "1k" / "aggregate" / "distinct"
    assert (case_dir / "setup.sql").exists()
    assert (case_dir / "original.sql").exists()
    assert (case_dir / "rewritten.sql").exists()
    benchmark_payload = json.loads((case_dir / "benchmark.json").read_text())
    assert benchmark_payload["artifact_type"] == "snowflake_benchmark"
    assert benchmark_payload["inputs"]["case_id"] == "aggregate-1k-distinct"

    suite_payload = json.loads(render_snowflake_family_suite_json(report))
    assert suite_payload["artifact_type"] == "snowflake_family_benchmark_suite"
    assert suite_payload["result_count"] == 5
    text = render_snowflake_family_suite_report(report).plain
    assert "Snowflake family benchmark suite" in text
    assert "aggregate-1k-distinct" in text


def test_classifies_near_threshold_disagreement_as_neutral_noisy(tmp_path) -> None:
    spec = next(
        case
        for case in snowflake_family_cases(scales=(1_000,), modes=("aggregate",))
        if case.rewrite_family == "pushdown"
    )
    benchmark = BenchmarkResult(
        status=BenchmarkStatus.COMPLETED,
        original=QueryBenchmark(
            status=BenchmarkStatus.COMPLETED,
            sql=spec.original_sql,
            median_ms=100.0,
            row_count=1,
            bytes_scanned=(100,),
            execution_time_ms=(94.0,),
        ),
        rewritten=QueryBenchmark(
            status=BenchmarkStatus.COMPLETED,
            sql=spec.rewritten_sql,
            median_ms=92.0,
            row_count=1,
            bytes_scanned=(100,),
            execution_time_ms=(100.0,),
        ),
        environment=_environment(),
        speedup=100.0 / 92.0,
        row_counts_match=True,
        timing_confident=True,
    )

    summary = summarize_snowflake_family_case(
        spec,
        run_index=1,
        benchmark=benchmark,
        benchmark_report_path=tmp_path / "benchmark.json",
        setup_path=tmp_path / "setup.sql",
        original_path=tmp_path / "original.sql",
        rewritten_path=tmp_path / "rewritten.sql",
    )

    assert summary.classification == "neutral_noisy"
    assert "no durable direction" in " ".join(summary.notes)


def _config() -> SnowflakeConnectionConfig:
    return SnowflakeConnectionConfig(
        account="acct",
        user="user",
        password="secret",
        warehouse="QSEAL_WH",
        database="QSEAL_DEV",
        schema="BENCHMARKS",
    )


def _environment() -> BenchmarkEnvironment:
    return BenchmarkEnvironment(
        engine="snowflake",
        python_version="3.12",
        platform="test",
        database_path="QSEAL_DEV.BENCHMARKS",
        threads=1,
        warmups=0,
        repetitions=1,
        timeout_seconds=30.0,
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
            self._rows = [("Aggregate Join Filter TableScan",)]
            return self
        if "QUERY_HISTORY_BY_SESSION" in normalized:
            query_id = params[0]
            self.sfqid = None
            self._one = (query_id, 100, 2.0, 10.0, 12.0, 1)
            return self
        if normalized.startswith(("USE ", "ALTER SESSION")):
            self.sfqid = None
            self._rows = []
            return self
        self.connection._counter += 1
        self.sfqid = f"q-{self.connection._counter}"
        self._rows = [(1,)]
        return self

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._one
