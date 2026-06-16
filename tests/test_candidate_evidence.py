from qseal.candidates.benchmarking import benchmark_pair
from qseal.candidates.explain import _diff_plans, explain_pair
from qseal.constraints.model import ConstraintCatalog, TableConstraints

UNIQUE_NON_NULL = ConstraintCatalog(
    tables={
        "users": TableConstraints(
            columns={"user_id": {"nullable": False}}, unique=[("user_id",)]
        )
    }
)


def test_benchmark_pair_runs_and_preserves_row_counts() -> None:
    # DISTINCT removal on a unique non-null key: equal row counts, so never
    # flagged suspect; outcome is one of the timing buckets.
    record = benchmark_pair(
        "SELECT DISTINCT user_id FROM users",
        "SELECT user_id FROM users",
        UNIQUE_NON_NULL,
        dialect="snowflake",
        scale=2000,
        warmups=0,
        repetitions=1,
        timeout=30.0,
    )
    assert record["outcome"] in {"faster", "neutral", "slower"}
    assert "speedup" in record


def test_benchmark_pair_flags_premise_violation_as_suspect() -> None:
    # Without the non-null+unique premise, DISTINCT actually removes rows on
    # synthetic data, so the row counts differ and the guard fires.
    record = benchmark_pair(
        "SELECT DISTINCT user_id FROM users",
        "SELECT user_id FROM users",
        ConstraintCatalog(),
        dialect="snowflake",
        scale=2000,
        warmups=0,
        repetitions=1,
        timeout=30.0,
    )
    assert record["outcome"] == "suspect"


def test_diff_plans_verdicts() -> None:
    distinct_plan = {"Operations": [[
        {"id": 0, "operation": "Result"},
        {"id": 1, "operation": "Aggregate"},
        {"id": 2, "operation": "TableScan"},
    ]]}
    plain_plan = {"Operations": [[
        {"id": 0, "operation": "Result"},
        {"id": 1, "operation": "TableScan"},
    ]]}

    eliminated = _diff_plans(distinct_plan, plain_plan)
    assert eliminated["verdict"] == "work_eliminated"
    assert eliminated["deltas"] == {"aggregate": -1}

    added = _diff_plans(plain_plan, distinct_plan)
    assert added["verdict"] == "work_added"

    same = _diff_plans(plain_plan, plain_plan)
    assert same["verdict"] == "no_plan_change"


class _FakeCursor:
    """Records DDL and returns a canned plan per EXPLAIN."""

    def __init__(self, plans):
        self._plans = list(plans)
        self.executed = []
        self._last = None

    def execute(self, sql):
        self.executed.append(sql)
        if sql.upper().startswith("EXPLAIN"):
            import json as _json

            self._last = _json.dumps(self._plans.pop(0))

    def fetchone(self):
        return (self._last,)


def test_explain_pair_diffs_plans_with_fake_cursor() -> None:
    distinct_plan = {"Operations": [[{"operation": "Aggregate"}, {"operation": "TableScan"}]]}
    plain_plan = {"Operations": [[{"operation": "TableScan"}]]}
    cursor = _FakeCursor([distinct_plan, plain_plan])

    record = explain_pair(
        cursor,
        "SELECT DISTINCT user_id FROM users",
        "SELECT user_id FROM users",
        UNIQUE_NON_NULL,
        "snowflake",
    )

    assert record["verdict"] == "work_eliminated"
    assert any(sql.startswith("CREATE OR REPLACE TABLE users") for sql in cursor.executed)
