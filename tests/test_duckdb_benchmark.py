import duckdb
import pytest

from qseal.benchmark.duckdb import benchmark_query, benchmark_query_pair
from qseal.benchmark.model import BenchmarkStatus

SETUP_SQL = """
CREATE TABLE users AS
SELECT value AS user_id, value % 5 AS status
FROM range(100) AS values(value);
"""


def test_benchmarks_query_pair_reproducibly() -> None:
    result = benchmark_query_pair(
        "SELECT DISTINCT user_id FROM users",
        "SELECT user_id FROM users",
        setup_sql=SETUP_SQL,
        warmups=1,
        repetitions=3,
        timeout_seconds=5,
        threads=1,
    )

    assert result.status == BenchmarkStatus.COMPLETED
    assert result.environment.duckdb_version == duckdb.__version__
    assert result.environment.threads == 1
    assert result.environment.warmups == 1
    assert result.environment.repetitions == 3
    assert len(result.original.timings_ms) == 3
    assert len(result.rewritten.timings_ms) == 3
    assert len(result.original.batch_timings_ms) == 3
    assert len(result.rewritten.batch_timings_ms) == 3
    assert result.original.median_ms is not None
    assert result.rewritten.median_ms is not None
    assert result.original.row_count == 100
    assert result.rewritten.row_count == 100
    assert result.row_counts_match is True
    assert result.speedup is not None
    assert "PROJECTION" in str(result.original.explain)


def test_benchmarks_absolute_query_state() -> None:
    result = benchmark_query(
        "SELECT user_id FROM users",
        setup_sql=SETUP_SQL,
        warmups=1,
        repetitions=3,
        minimum_duration_ms=5,
    )

    assert result.status == BenchmarkStatus.COMPLETED
    assert result.query.median_ms is not None
    assert result.query.executions_per_sample > 1
    assert len(result.query.timings_ms) == 3
    assert result.query.row_count == 100
    assert result.timing_confident is True


def test_reports_duckdb_query_errors() -> None:
    result = benchmark_query_pair(
        "SELECT user_id FROM missing_users",
        "SELECT user_id FROM missing_users",
        warmups=0,
        repetitions=1,
    )

    assert result.status == BenchmarkStatus.ERROR
    assert "missing_users" in str(result.reason)
    assert result.speedup is None
    assert result.row_counts_match is None


def test_batches_fast_queries_to_reach_minimum_sample_duration() -> None:
    result = benchmark_query_pair(
        "SELECT DISTINCT user_id FROM users",
        "SELECT user_id FROM users",
        setup_sql=SETUP_SQL,
        warmups=0,
        repetitions=1,
        minimum_duration_ms=5,
    )

    assert result.status == BenchmarkStatus.COMPLETED
    assert result.speedup is not None
    assert result.timing_confident is True
    assert result.environment.minimum_duration_ms == 5
    assert result.original.executions_per_sample > 1
    assert result.rewritten.executions_per_sample > 1
    assert result.original.batch_timings_ms
    assert result.rewritten.batch_timings_ms


def test_marks_timing_low_confidence_when_batch_cap_cannot_reach_target() -> None:
    result = benchmark_query_pair(
        "SELECT 1",
        "SELECT 1",
        warmups=0,
        repetitions=1,
        minimum_duration_ms=10_000,
    )

    assert result.status == BenchmarkStatus.COMPLETED
    assert result.speedup is not None
    assert result.timing_confident is False
    assert result.original.executions_per_sample == 1000
    assert result.rewritten.executions_per_sample == 1000
    assert "safety cap" in str(result.confidence_reason)


def test_interrupts_queries_that_exceed_timeout() -> None:
    result = benchmark_query_pair(
        "SELECT sum(a.i * b.i) FROM range(1000000) a(i), range(1000000) b(i)",
        "SELECT 1",
        warmups=0,
        repetitions=1,
        timeout_seconds=0.001,
    )

    assert result.status == BenchmarkStatus.TIMEOUT
    assert "0.001 second timeout" in str(result.reason)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"warmups": -1}, "warmups"),
        ({"repetitions": 0}, "repetitions"),
        ({"timeout_seconds": 0}, "timeout_seconds"),
        ({"threads": 0}, "threads"),
        ({"minimum_duration_ms": -1}, "minimum_duration_ms"),
    ],
)
def test_rejects_invalid_benchmark_settings(kwargs, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        benchmark_query_pair("SELECT 1", "SELECT 1", **kwargs)
