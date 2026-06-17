import json
from pathlib import Path

from click.testing import CliRunner

from qseal.cli import main

DEMO = Path("examples/product_demo")


def test_product_demo_dbt_scan_finds_guarded_rewrites() -> None:
    result = CliRunner().invoke(
        main,
        ["dbt", "scan", str(DEMO / "dbt_project"), "--format", "json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["summary"]["model_count"] == 2
    assert payload["summary"]["proven_finding_count"] == 2

    by_rule = {
        suggestion["rule_name"]: suggestion
        for result_row in payload["results"]
        for suggestion in result_row["suggestions"]
    }
    distinct = by_rule["remove_redundant_distinct"]
    assert "dbt test: unique on dim_users.user_id" in distinct["required_tests"]
    assert "dbt test: not_null on dim_users.user_id" in distinct["required_tests"]

    left_join = by_rule["remove_unused_left_join"]
    assert left_join["required_tests"] == ["dbt test: unique on dim_users.user_id"]
    assert "LEFT JOIN dim_users" in left_join["original_sql"]
    assert "LEFT JOIN" not in left_join["rewritten_sql"]


def test_product_demo_dbt_scan_text_is_review_grouped() -> None:
    result = CliRunner().invoke(
        main,
        ["dbt", "scan", str(DEMO / "dbt_project"), "--format", "text"],
    )

    assert result.exit_code == 0, result.output
    assert "Safe and apply-ready (2)" in result.output
    assert "Safe, manual review needed (0)" in result.output
    assert "Rejected, unsupported, or informational (0)" in result.output
    assert "Required tests:" in result.output
    assert "remove_unused_left_join" in result.output
    assert "dbt_project/models/fct_orders.sql" in result.output
    assert "Recommendation: review generated diff" in result.output
    assert "Diff:" in result.output
    assert "-SELECT DISTINCT user_id" in result.output
    assert "-LEFT JOIN dim_users AS dim_users" in result.output


def test_product_demo_candidate_evidence_benchmarks_only_proven_candidate() -> None:
    result = CliRunner().invoke(
        main,
        [
            "candidates",
            "evidence",
            str(DEMO / "original.sql"),
            "--candidates-dir",
            str(DEMO / "candidates"),
            "--schema",
            str(DEMO / "dbt_project" / "models" / "schema.yml"),
            "--rows",
            "1000",
            "--warmups",
            "0",
            "--repetitions",
            "1",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["candidate_count"] == 2
    assert payload["proven_count"] == 1
    assert payload["benchmarked_count"] == 1

    by_name = {Path(row["candidate_path"]).name: row for row in payload["results"]}
    assert by_name["001_remove_distinct.sql"]["proven"] is True
    assert by_name["001_remove_distinct.sql"]["benchmark"] is not None
    assert by_name["001_remove_distinct.sql"]["review_section"] in {
        "safe_worth_considering",
        "safe_no_clear_speedup",
    }
    assert by_name["001_remove_distinct.sql"]["required_tests"] == [
        "dbt test: unique on dim_users.user_id",
        "dbt test: not_null on dim_users.user_id",
    ]
    assert "-SELECT DISTINCT user_id" in by_name["001_remove_distinct.sql"]["review_diff"]
    assert by_name["002_filter_rows.sql"]["proven"] is False
    assert by_name["002_filter_rows.sql"]["benchmark"] is None
    assert by_name["002_filter_rows.sql"]["review_section"] == "rejected_unproven"
    assert by_name["002_filter_rows.sql"]["recommendation"] == "do_not_apply_unproven"


def test_product_demo_candidate_evidence_text_is_review_grouped() -> None:
    result = CliRunner().invoke(
        main,
        [
            "candidates",
            "evidence",
            str(DEMO / "original.sql"),
            "--candidates-dir",
            str(DEMO / "candidates"),
            "--schema",
            str(DEMO / "dbt_project" / "models" / "schema.yml"),
            "--rows",
            "1000",
            "--warmups",
            "0",
            "--repetitions",
            "1",
            "--format",
            "text",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Safe and worth considering (1)" in result.output
    assert "Rejected or unproven (1)" in result.output
    assert "Required tests:" in result.output
    assert "Diff:" in result.output
    assert "Recommendation: do not apply; not proven" in result.output


def test_product_demo_direct_benchmark_pair_completes() -> None:
    result = CliRunner().invoke(
        main,
        [
            "benchmark",
            str(DEMO / "original.sql"),
            str(DEMO / "candidates" / "001_remove_distinct.sql"),
            "--setup",
            str(DEMO / "setup.sql"),
            "--warmups",
            "0",
            "--repetitions",
            "1",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["artifact_type"] == "duckdb_benchmark"
    assert payload["status"] == "COMPLETED"
    assert payload["row_counts_match"] is True
