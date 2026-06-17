import json
from pathlib import Path

from click.testing import CliRunner

from qseal.candidates.benchmarking import benchmark_pair
from qseal.candidates.explain import _diff_plans, explain_pair
from qseal.cli import main
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


def test_candidates_evidence_cli_benchmarks_only_proven_candidates(tmp_path) -> None:
    original = tmp_path / "original.sql"
    schema = tmp_path / "schema.yml"
    candidates = tmp_path / "candidates"
    report = tmp_path / "evidence.json"
    candidates.mkdir()
    proven = candidates / "001_drop_distinct.sql"
    unproven = candidates / "002_filter_rows.sql"

    original.write_text("SELECT DISTINCT user_id FROM users")
    proven.write_text("SELECT user_id FROM users")
    unproven.write_text("SELECT user_id FROM users WHERE user_id > 10")
    schema.write_text(
        """
tables:
  users:
    columns:
      user_id:
        nullable: false
    unique:
      - [user_id]
"""
    )
    (candidates / "metadata.json").write_text(
        json.dumps(
            {
                "candidates": [
                    {"path": proven.name, "description": "safe distinct removal"},
                    {"path": unproven.name, "description": "unsafe filter"},
                ]
            }
        )
    )

    result = CliRunner().invoke(
        main,
        [
            "candidates",
            "evidence",
            str(original),
            "--candidates-dir",
            str(candidates),
            "--schema",
            str(schema),
            "--rows",
            "1000",
            "--warmups",
            "0",
            "--repetitions",
            "1",
            "--report-file",
            str(report),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(report.read_text())
    assert payload["artifact_type"] == "candidate_evidence"
    assert payload["candidate_count"] == 2
    assert payload["proven_count"] == 1
    assert payload["benchmarked_count"] == 1

    by_name = {Path(row["candidate_path"]).name: row for row in payload["results"]}
    assert by_name[proven.name]["proven"] is True
    assert by_name[proven.name]["benchmark"]["outcome"] in {
        "faster",
        "neutral",
        "slower",
    }
    assert by_name[proven.name]["review_section"] in {
        "safe_worth_considering",
        "safe_no_clear_speedup",
    }
    assert by_name[proven.name]["required_tests"] == [
        "dbt test: unique on users.user_id",
        "dbt test: not_null on users.user_id",
    ]
    assert "-SELECT DISTINCT user_id" in by_name[proven.name]["review_diff"]
    assert by_name[unproven.name]["proven"] is False
    assert by_name[unproven.name]["benchmark"] is None
    assert by_name[unproven.name]["review_section"] == "rejected_unproven"
    assert by_name[unproven.name]["review_diff"] is None
    assert by_name[unproven.name]["recommendation"] == "do_not_apply_unproven"


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
