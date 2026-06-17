import json
from pathlib import Path

from click.testing import CliRunner

from qseal.cli import main

DEMO = Path("examples/product_demo")


def test_product_demo_dbt_scan_finds_guarded_distinct_rewrite() -> None:
    result = CliRunner().invoke(
        main,
        ["dbt", "scan", str(DEMO / "dbt_project"), "--format", "json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["summary"]["proven_finding_count"] == 1
    suggestion = payload["results"][0]["suggestions"][0]
    assert suggestion["rule_name"] == "remove_redundant_distinct"
    assert "dbt test: unique on dim_users.user_id" in suggestion["required_tests"]
    assert "dbt test: not_null on dim_users.user_id" in suggestion["required_tests"]


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
    assert by_name["002_filter_rows.sql"]["proven"] is False
    assert by_name["002_filter_rows.sql"]["benchmark"] is None
    assert by_name["002_filter_rows.sql"]["recommendation"] == "do_not_apply_unproven"


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
