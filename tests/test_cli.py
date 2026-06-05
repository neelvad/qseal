import json
from pathlib import Path

from click.testing import CliRunner

from snowprove.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


def test_suggest_cli(tmp_path) -> None:
    query = tmp_path / "query.sql"
    schema = tmp_path / "schema.yml"
    query.write_text("SELECT DISTINCT user_id FROM users")
    schema.write_text(
        """
tables:
  users:
    unique:
      - [user_id]
"""
    )

    result = CliRunner().invoke(main, ["suggest", str(query), "--schema", str(schema)])

    assert result.exit_code == 0
    assert "PROVEN_EQUIVALENT" in result.output
    assert "SELECT user_id" in result.output


def test_check_cli(tmp_path) -> None:
    original = tmp_path / "original.sql"
    rewritten = tmp_path / "rewritten.sql"
    schema = tmp_path / "schema.yml"
    original.write_text("SELECT DISTINCT user_id FROM users")
    rewritten.write_text("SELECT user_id FROM users")
    schema.write_text(
        """
tables:
  users:
    unique:
      - [user_id]
"""
    )

    result = CliRunner().invoke(
        main,
        ["check", str(original), str(rewritten), "--schema", str(schema)],
    )

    assert result.exit_code == 0
    assert "PROVEN_EQUIVALENT" in result.output


def test_suggest_cli_reports_unsupported_sql(tmp_path) -> None:
    query = tmp_path / "query.sql"
    schema = tmp_path / "schema.yml"
    query.write_text("SELECT user_id FROM users JOIN orders USING (user_id)")
    schema.write_text("tables: {}\n")

    result = CliRunner().invoke(main, ["suggest", str(query), "--schema", str(schema)])

    assert result.exit_code == 0
    assert "UNSUPPORTED" in result.output
    assert "JOIN conditions must be column equality predicates" in result.output


def test_check_cli_reports_unsupported_original_sql(tmp_path) -> None:
    original = tmp_path / "original.sql"
    rewritten = tmp_path / "rewritten.sql"
    schema = tmp_path / "schema.yml"
    original.write_text("SELECT user_id FROM users JOIN orders USING (user_id)")
    rewritten.write_text("SELECT user_id FROM users")
    schema.write_text("tables: {}\n")

    result = CliRunner().invoke(
        main,
        ["check", str(original), str(rewritten), "--schema", str(schema)],
    )

    assert result.exit_code == 0
    assert "UNSUPPORTED" in result.output
    assert "Original query unsupported" in result.output


def test_suggest_cli_reports_predicate_pushdown(tmp_path) -> None:
    query = tmp_path / "query.sql"
    schema = tmp_path / "schema.yml"
    query.write_text(
        """
        SELECT user_id, revenue
        FROM (
          SELECT user_id, revenue
          FROM orders
        ) x
        WHERE revenue > 0
        """
    )
    schema.write_text("tables: {}\n")

    result = CliRunner().invoke(main, ["suggest", str(query), "--schema", str(schema)])

    assert result.exit_code == 0
    assert "predicate_pushdown" in result.output
    assert "SELECT user_id, revenue" in result.output


def test_suggest_cli_reports_join_elimination(tmp_path) -> None:
    query = tmp_path / "query.sql"
    schema = tmp_path / "schema.yml"
    query.write_text(
        """
        SELECT f.user_id, f.revenue
        FROM fact_orders f
        LEFT JOIN dim_users u ON f.user_id = u.user_id
        """
    )
    schema.write_text(
        """
tables:
  dim_users:
    unique:
      - [user_id]
"""
    )

    result = CliRunner().invoke(main, ["suggest", str(query), "--schema", str(schema)])

    assert result.exit_code == 0
    assert "remove_unused_left_join" in result.output
    assert "FROM fact_orders f" in result.output


def test_suggest_cli_reports_join_distinct_to_exists(tmp_path) -> None:
    query = tmp_path / "query.sql"
    schema = tmp_path / "schema.yml"
    query.write_text(
        """
        SELECT DISTINCT u.user_id
        FROM users u
        JOIN orders o ON u.user_id = o.user_id
        """
    )
    schema.write_text("tables: {}\n")

    result = CliRunner().invoke(main, ["suggest", str(query), "--schema", str(schema)])

    assert result.exit_code == 0
    assert "rewrite_join_distinct_to_exists" in result.output
    assert "WHERE EXISTS" in result.output


def test_suggest_cli_can_report_all_applicable_results(tmp_path) -> None:
    query = tmp_path / "query.sql"
    schema = tmp_path / "schema.yml"
    query.write_text(
        """
        SELECT DISTINCT user_id
        FROM (
          SELECT user_id
          FROM users
        ) x
        WHERE user_id = 1
        """
    )
    schema.write_text("tables: {}\n")

    result = CliRunner().invoke(main, ["suggest", str(query), "--schema", str(schema), "--all"])

    assert result.exit_code == 0
    assert "remove_redundant_distinct" in result.output
    assert "predicate_pushdown" in result.output


def test_suggest_cli_can_report_json(tmp_path) -> None:
    query = tmp_path / "query.sql"
    schema = tmp_path / "schema.yml"
    query.write_text("SELECT DISTINCT user_id FROM users")
    schema.write_text(
        """
tables:
  users:
    unique:
      - [user_id]
"""
    )

    result = CliRunner().invoke(
        main,
        ["suggest", str(query), "--schema", str(schema), "--format", "json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["artifact_type"] == "suggestion"
    assert payload["status"] == "PROVEN_EQUIVALENT"
    assert payload["rule_name"] == "remove_redundant_distinct"


def test_suggest_cli_can_report_all_json(tmp_path) -> None:
    query = tmp_path / "query.sql"
    schema = tmp_path / "schema.yml"
    query.write_text(
        """
        SELECT DISTINCT user_id
        FROM (
          SELECT user_id
          FROM users
        ) x
        WHERE user_id = 1
        """
    )
    schema.write_text("tables: {}\n")

    result = CliRunner().invoke(
        main,
        ["suggest", str(query), "--schema", str(schema), "--all", "--format", "json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["artifact_type"] == "suggestions"
    assert [item["rule_name"] for item in payload["results"]] == [
        "remove_redundant_distinct",
        "predicate_pushdown",
    ]


def test_check_cli_can_report_json(tmp_path) -> None:
    original = tmp_path / "original.sql"
    rewritten = tmp_path / "rewritten.sql"
    schema = tmp_path / "schema.yml"
    original.write_text("SELECT DISTINCT user_id FROM users")
    rewritten.write_text("SELECT user_id FROM users")
    schema.write_text(
        """
tables:
  users:
    unique:
      - [user_id]
"""
    )

    result = CliRunner().invoke(
        main,
        ["check", str(original), str(rewritten), "--schema", str(schema), "--format", "json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["artifact_type"] == "verification"
    assert payload["proven"] is True
    assert payload["status"] == "PROVEN_EQUIVALENT"
    assert payload["rule_name"] == "remove_redundant_distinct"
    assert payload["inputs"]["original_path"] == str(original)
    assert payload["inputs"]["rewritten_path"] == str(rewritten)
    assert payload["inputs"]["schema_path"] == str(schema)
    assert payload["inputs"]["schema_format"] == "auto"


def test_check_cli_can_fail_on_unproven(tmp_path) -> None:
    original = tmp_path / "original.sql"
    rewritten = tmp_path / "rewritten.sql"
    schema = tmp_path / "schema.yml"
    original.write_text("SELECT DISTINCT user_id FROM users")
    rewritten.write_text("SELECT user_id FROM users")
    schema.write_text("tables: {}\n")

    result = CliRunner().invoke(
        main,
        [
            "check",
            str(original),
            str(rewritten),
            "--schema",
            str(schema),
            "--fail-on",
            "unproven",
        ],
    )

    assert result.exit_code == 1
    assert "NOT_EQUIVALENT" in result.output


def test_check_cli_accepts_builtin_verifier_backend(tmp_path) -> None:
    original = tmp_path / "original.sql"
    rewritten = tmp_path / "rewritten.sql"
    schema = tmp_path / "schema.yml"
    original.write_text("SELECT DISTINCT user_id FROM users")
    rewritten.write_text("SELECT user_id FROM users")
    schema.write_text(
        """
tables:
  users:
    unique:
      - [user_id]
"""
    )

    result = CliRunner().invoke(
        main,
        [
            "check",
            str(original),
            str(rewritten),
            "--schema",
            str(schema),
            "--verifier",
            "builtin",
        ],
    )

    assert result.exit_code == 0
    assert "PROVEN_EQUIVALENT" in result.output


def test_check_cli_does_not_fail_on_proven_with_unproven_policy(tmp_path) -> None:
    original = tmp_path / "original.sql"
    rewritten = tmp_path / "rewritten.sql"
    schema = tmp_path / "schema.yml"
    original.write_text("SELECT DISTINCT user_id FROM users")
    rewritten.write_text("SELECT user_id FROM users")
    schema.write_text(
        """
tables:
  users:
    unique:
      - [user_id]
"""
    )

    result = CliRunner().invoke(
        main,
        [
            "check",
            str(original),
            str(rewritten),
            "--schema",
            str(schema),
            "--fail-on",
            "unproven",
        ],
    )

    assert result.exit_code == 0
    assert "PROVEN_EQUIVALENT" in result.output


def test_candidates_check_cli_reports_multiple_candidates(tmp_path) -> None:
    original = tmp_path / "original.sql"
    candidate_a = tmp_path / "candidate_a.sql"
    candidate_b = tmp_path / "candidate_b.sql"
    schema = tmp_path / "schema.yml"
    original.write_text("SELECT DISTINCT user_id FROM users")
    candidate_a.write_text("SELECT user_id FROM users")
    candidate_b.write_text("SELECT user_id FROM users WHERE status = 'active'")
    schema.write_text(
        """
tables:
  users:
    unique:
      - [user_id]
"""
    )

    result = CliRunner().invoke(
        main,
        [
            "candidates",
            "check",
            str(original),
            str(candidate_a),
            str(candidate_b),
            "--schema",
            str(schema),
        ],
    )

    assert result.exit_code == 0
    assert "Candidates checked: 2" in result.output
    assert "Proven: 1" in result.output
    assert candidate_a.name in result.output
    assert "PROVEN_EQUIVALENT" in result.output
    assert candidate_b.name in result.output
    assert "UNKNOWN" in result.output


def test_candidates_generate_cli_writes_proven_rewrite_candidates(tmp_path) -> None:
    query = tmp_path / "query.sql"
    schema = tmp_path / "schema.yml"
    output_dir = tmp_path / "candidates"
    query.write_text("SELECT DISTINCT user_id FROM users")
    schema.write_text(
        """
tables:
  users:
    unique:
      - [user_id]
"""
    )

    result = CliRunner().invoke(
        main,
        [
            "candidates",
            "generate",
            str(query),
            "--schema",
            str(schema),
            "--out",
            str(output_dir),
        ],
    )

    candidate = output_dir / "001_remove_redundant_distinct.sql"
    assert result.exit_code == 0
    assert "Candidates generated: 1" in result.output
    assert candidate.exists()
    assert candidate.read_text() == "SELECT user_id\nFROM users;\n"


def test_candidates_generate_cli_can_report_json(tmp_path) -> None:
    query = tmp_path / "query.sql"
    schema = tmp_path / "schema.yml"
    output_dir = tmp_path / "candidates"
    query.write_text("SELECT DISTINCT user_id FROM users")
    schema.write_text(
        """
tables:
  users:
    unique:
      - [user_id]
"""
    )

    result = CliRunner().invoke(
        main,
        [
            "candidates",
            "generate",
            str(query),
            "--schema",
            str(schema),
            "--out",
            str(output_dir),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["artifact_type"] == "candidate_generation"
    assert payload["generated_count"] == 1
    assert payload["skipped_count"] == 0
    assert payload["generated"][0]["rule_name"] == "remove_redundant_distinct"
    assert payload["generated"][0]["status"] == "PROVEN_EQUIVALENT"


def test_candidates_generate_cli_refuses_to_overwrite_without_force(tmp_path) -> None:
    query = tmp_path / "query.sql"
    schema = tmp_path / "schema.yml"
    output_dir = tmp_path / "candidates"
    output_dir.mkdir()
    candidate = output_dir / "001_remove_redundant_distinct.sql"
    candidate.write_text("SELECT existing FROM users\n")
    query.write_text("SELECT DISTINCT user_id FROM users")
    schema.write_text(
        """
tables:
  users:
    unique:
      - [user_id]
"""
    )

    result = CliRunner().invoke(
        main,
        [
            "candidates",
            "generate",
            str(query),
            "--schema",
            str(schema),
            "--out",
            str(output_dir),
        ],
    )

    assert result.exit_code == 1
    assert "Candidate file already exists" in result.output
    assert candidate.read_text() == "SELECT existing FROM users\n"


def test_candidates_generate_then_check_cli(tmp_path) -> None:
    query = tmp_path / "query.sql"
    schema = tmp_path / "schema.yml"
    output_dir = tmp_path / "candidates"
    query.write_text("SELECT DISTINCT user_id FROM users")
    schema.write_text(
        """
tables:
  users:
    unique:
      - [user_id]
"""
    )

    generate = CliRunner().invoke(
        main,
        [
            "candidates",
            "generate",
            str(query),
            "--schema",
            str(schema),
            "--out",
            str(output_dir),
        ],
    )
    check = CliRunner().invoke(
        main,
        [
            "candidates",
            "check",
            str(query),
            str(output_dir / "001_remove_redundant_distinct.sql"),
            "--schema",
            str(schema),
            "--fail-on",
            "unproven",
        ],
    )

    assert generate.exit_code == 0
    assert check.exit_code == 0
    assert "Proven: 1" in check.output


def test_candidates_check_cli_accepts_candidates_dir(tmp_path) -> None:
    original = tmp_path / "original.sql"
    candidates_dir = tmp_path / "candidates"
    schema = tmp_path / "schema.yml"
    candidates_dir.mkdir()
    original.write_text("SELECT DISTINCT user_id FROM users")
    (candidates_dir / "001_remove_redundant_distinct.sql").write_text(
        "SELECT user_id\nFROM users;\n"
    )
    schema.write_text(
        """
tables:
  users:
    unique:
      - [user_id]
"""
    )

    result = CliRunner().invoke(
        main,
        [
            "candidates",
            "check",
            str(original),
            "--candidates-dir",
            str(candidates_dir),
            "--schema",
            str(schema),
        ],
    )

    assert result.exit_code == 0
    assert "Candidates checked: 1" in result.output
    assert "Proven: 1" in result.output


def test_candidates_run_cli_generates_and_checks_candidates(tmp_path) -> None:
    query = tmp_path / "query.sql"
    schema = tmp_path / "schema.yml"
    output_dir = tmp_path / "candidates"
    query.write_text("SELECT DISTINCT user_id FROM users")
    schema.write_text(
        """
tables:
  users:
    unique:
      - [user_id]
"""
    )

    result = CliRunner().invoke(
        main,
        [
            "candidates",
            "run",
            str(query),
            "--schema",
            str(schema),
            "--out",
            str(output_dir),
            "--fail-on",
            "unproven",
        ],
    )

    assert result.exit_code == 0
    assert "Candidates generated: 1" in result.output
    assert "Candidates checked: 1" in result.output
    assert "Proven: 1" in result.output
    assert (output_dir / "001_remove_redundant_distinct.sql").exists()


def test_candidates_run_cli_can_report_json(tmp_path) -> None:
    query = tmp_path / "query.sql"
    schema = tmp_path / "schema.yml"
    output_dir = tmp_path / "candidates"
    query.write_text("SELECT DISTINCT user_id FROM users")
    schema.write_text(
        """
tables:
  users:
    unique:
      - [user_id]
"""
    )

    result = CliRunner().invoke(
        main,
        [
            "candidates",
            "run",
            str(query),
            "--schema",
            str(schema),
            "--out",
            str(output_dir),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["artifact_type"] == "candidate_run"
    assert payload["generation"]["generated_count"] == 1
    assert payload["verification"]["result_count"] == 1
    assert payload["verification"]["proven_count"] == 1


def test_candidates_run_cli_can_write_report_file(tmp_path) -> None:
    query = tmp_path / "query.sql"
    schema = tmp_path / "schema.yml"
    output_dir = tmp_path / "candidates"
    report_file = tmp_path / "reports" / "candidate-run.json"
    query.write_text("SELECT DISTINCT user_id FROM users")
    schema.write_text(
        """
tables:
  users:
    unique:
      - [user_id]
"""
    )

    result = CliRunner().invoke(
        main,
        [
            "candidates",
            "run",
            str(query),
            "--schema",
            str(schema),
            "--out",
            str(output_dir),
            "--report-file",
            str(report_file),
        ],
    )

    assert result.exit_code == 0
    assert "Candidates generated: 1" in result.output
    assert f"Report file written: {report_file}" in result.stderr
    payload = json.loads(report_file.read_text())
    assert payload["artifact_type"] == "candidate_run"
    assert payload["generation"]["generated_count"] == 1
    assert payload["verification"]["proven_count"] == 1


def test_candidates_run_cli_can_fail_when_no_candidates_are_generated(tmp_path) -> None:
    query = tmp_path / "query.sql"
    schema = tmp_path / "schema.yml"
    output_dir = tmp_path / "candidates"
    query.write_text("SELECT user_id FROM users")
    schema.write_text("tables: {}\n")

    result = CliRunner().invoke(
        main,
        [
            "candidates",
            "run",
            str(query),
            "--schema",
            str(schema),
            "--out",
            str(output_dir),
            "--fail-on",
            "unproven",
        ],
    )

    assert result.exit_code == 1
    assert "Candidates generated: 0" in result.output


def test_candidates_check_cli_can_report_json(tmp_path) -> None:
    original = tmp_path / "original.sql"
    candidate = tmp_path / "candidate.sql"
    schema = tmp_path / "schema.yml"
    original.write_text("SELECT DISTINCT user_id FROM users")
    candidate.write_text("SELECT user_id FROM users")
    schema.write_text(
        """
tables:
  users:
    unique:
      - [user_id]
"""
    )

    result = CliRunner().invoke(
        main,
        [
            "candidates",
            "check",
            str(original),
            str(candidate),
            "--schema",
            str(schema),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["artifact_type"] == "candidate_verifications"
    assert payload["result_count"] == 1
    assert payload["proven_count"] == 1
    assert payload["results"][0]["proven"] is True
    assert payload["results"][0]["inputs"]["rewritten_path"] == str(candidate)


def test_candidates_check_cli_can_fail_on_unproven(tmp_path) -> None:
    original = tmp_path / "original.sql"
    candidate = tmp_path / "candidate.sql"
    schema = tmp_path / "schema.yml"
    original.write_text("SELECT DISTINCT user_id FROM users")
    candidate.write_text("SELECT user_id FROM users")
    schema.write_text("tables: {}\n")

    result = CliRunner().invoke(
        main,
        [
            "candidates",
            "check",
            str(original),
            str(candidate),
            "--schema",
            str(schema),
            "--fail-on",
            "unproven",
        ],
    )

    assert result.exit_code == 1
    assert "NOT_EQUIVALENT" in result.output


def test_dbt_scan_cli_runs_jaffle_like_fixture_json() -> None:
    project = FIXTURES / "dbt_projects" / "jaffle_like"

    result = CliRunner().invoke(
        main,
        ["dbt", "scan", str(project), "--all", "--format", "json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["artifact_type"] == "dbt_scan"
    assert payload["model_count"] == 5
    assert payload["summary"]["proven_finding_count"] == 1
    assert payload["summary"]["status_counts"] == {
        "PROVEN_EQUIVALENT": 1,
        "UNSUPPORTED": 2,
    }


def test_candidates_check_cli_runs_checked_in_fixture_json() -> None:
    fixture = FIXTURES / "candidates"
    original = fixture / "original.sql"
    candidates = [
        fixture / "candidate_distinct_removed.sql",
        fixture / "candidate_filtered.sql",
    ]

    result = CliRunner().invoke(
        main,
        [
            "candidates",
            "check",
            str(original),
            *(str(candidate) for candidate in candidates),
            "--schema",
            str(fixture / "schema.yml"),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["artifact_type"] == "candidate_verifications"
    assert payload["result_count"] == 2
    assert payload["proven_count"] == 1
    assert [item["status"] for item in payload["results"]] == [
        "PROVEN_EQUIVALENT",
        "UNKNOWN",
    ]


def test_candidates_check_cli_fixture_can_fail_on_unproven() -> None:
    fixture = FIXTURES / "candidates"

    result = CliRunner().invoke(
        main,
        [
            "candidates",
            "check",
            str(fixture / "original.sql"),
            str(fixture / "candidate_distinct_removed.sql"),
            str(fixture / "candidate_filtered.sql"),
            "--schema",
            str(fixture / "schema.yml"),
            "--fail-on",
            "unproven",
        ],
    )

    assert result.exit_code == 1
    assert "Candidates checked: 2" in result.output
    assert "UNKNOWN" in result.output


def test_check_cli_external_verifier_stub_reports_unsupported(tmp_path) -> None:
    original = tmp_path / "original.sql"
    rewritten = tmp_path / "rewritten.sql"
    schema = tmp_path / "schema.yml"
    original.write_text("SELECT DISTINCT user_id FROM users")
    rewritten.write_text("SELECT user_id FROM users")
    schema.write_text(
        """
tables:
  users:
    unique:
      - [user_id]
"""
    )

    result = CliRunner().invoke(
        main,
        [
            "check",
            str(original),
            str(rewritten),
            "--schema",
            str(schema),
            "--verifier",
            "external",
            "--solver-command",
            "qed",
        ],
    )

    assert result.exit_code == 0
    assert "UNSUPPORTED" in result.output
    assert "qed integration is not implemented yet" in result.output


def test_suggest_cli_can_load_dbt_schema_format(tmp_path) -> None:
    query = tmp_path / "query.sql"
    schema = tmp_path / "schema.yml"
    query.write_text("SELECT DISTINCT user_id FROM dim_users")
    schema.write_text(
        """
version: 2
models:
  - name: dim_users
    columns:
      - name: user_id
        tests:
          - unique
"""
    )

    result = CliRunner().invoke(
        main,
        [
            "suggest",
            str(query),
            "--schema",
            str(schema),
            "--schema-format",
            "dbt",
        ],
    )

    assert result.exit_code == 0
    assert "PROVEN_EQUIVALENT" in result.output


def test_suggest_cli_auto_detects_dbt_schema_format(tmp_path) -> None:
    query = tmp_path / "query.sql"
    schema = tmp_path / "schema.yml"
    query.write_text("SELECT DISTINCT user_id FROM dim_users")
    schema.write_text(
        """
version: 2
models:
  - name: dim_users
    columns:
      - name: user_id
        tests:
          - unique
"""
    )

    result = CliRunner().invoke(main, ["suggest", str(query), "--schema", str(schema)])

    assert result.exit_code == 0
    assert "PROVEN_EQUIVALENT" in result.output


def test_suggest_cli_can_select_rule(tmp_path) -> None:
    query = tmp_path / "query.sql"
    schema = tmp_path / "schema.yml"
    query.write_text(
        """
        SELECT user_id, revenue
        FROM (
          SELECT user_id, revenue
          FROM orders
        ) x
        WHERE revenue > 0
        """
    )
    schema.write_text("tables: {}\n")

    result = CliRunner().invoke(
        main,
        [
            "suggest",
            str(query),
            "--schema",
            str(schema),
            "--rule",
            "predicate_pushdown",
        ],
    )

    assert result.exit_code == 0
    assert "predicate_pushdown" in result.output


def test_suggest_cli_reports_not_null_filter_removal_from_dbt_schema(tmp_path) -> None:
    query = tmp_path / "query.sql"
    schema = tmp_path / "schema.yml"
    query.write_text("SELECT user_id FROM users WHERE email IS NOT NULL")
    schema.write_text(
        """
version: 2
models:
  - name: users
    columns:
      - name: email
        tests:
          - not_null
"""
    )

    result = CliRunner().invoke(main, ["suggest", str(query), "--schema", str(schema)])

    assert result.exit_code == 0
    assert "remove_redundant_not_null_filter" in result.output
    assert "SELECT user_id" in result.output


def test_suggest_cli_rejects_unknown_rule(tmp_path) -> None:
    query = tmp_path / "query.sql"
    schema = tmp_path / "schema.yml"
    query.write_text("SELECT user_id FROM users")
    schema.write_text("tables: {}\n")

    result = CliRunner().invoke(
        main,
        ["suggest", str(query), "--schema", str(schema), "--rule", "missing"],
    )

    assert result.exit_code != 0
    assert "Invalid value for '--rule'" in result.output


def test_dbt_scan_cli_reports_findings(tmp_path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "dim_users.sql").write_text("SELECT DISTINCT user_id FROM dim_users")
    (models / "schema.yml").write_text(
        """
version: 2
models:
  - name: dim_users
    columns:
      - name: user_id
        tests:
          - unique
"""
    )

    result = CliRunner().invoke(main, ["dbt", "scan", str(tmp_path)])

    assert result.exit_code == 0
    assert "Scanned models: 1" in result.output
    assert "Findings: 1" in result.output
    assert "Summary:" in result.output
    assert "remove_redundant_distinct: 1" in result.output
    assert "remove_redundant_distinct" in result.output


def test_dbt_scan_cli_reports_json(tmp_path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "dim_users.sql").write_text("SELECT DISTINCT user_id FROM dim_users")
    (models / "schema.yml").write_text(
        """
version: 2
models:
  - name: dim_users
    columns:
      - name: user_id
        tests:
          - unique
"""
    )

    result = CliRunner().invoke(main, ["dbt", "scan", str(tmp_path), "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["model_count"] == 1
    assert payload["summary"]["proven_finding_count"] == 1
    assert payload["summary"]["rule_counts"]["remove_redundant_distinct"] == 1
    assert payload["results"][0]["suggestions"][0]["rule_name"] == "remove_redundant_distinct"


def test_dbt_scan_cli_writes_report_file(tmp_path) -> None:
    models = tmp_path / "models"
    report = tmp_path / "artifacts" / "snowprove.json"
    models.mkdir()
    (models / "dim_users.sql").write_text("SELECT DISTINCT user_id FROM dim_users")
    (models / "schema.yml").write_text(
        """
version: 2
models:
  - name: dim_users
    columns:
      - name: user_id
        tests:
          - unique
"""
    )

    result = CliRunner().invoke(
        main,
        ["dbt", "scan", str(tmp_path), "--report-file", str(report)],
    )

    assert result.exit_code == 0
    assert "Report file written:" in result.output
    payload = json.loads(report.read_text())
    assert payload["artifact_type"] == "dbt_scan"
    assert payload["summary"]["proven_finding_count"] == 1


def test_dbt_scan_cli_can_write_report_file_with_json_stdout(tmp_path) -> None:
    models = tmp_path / "models"
    report = tmp_path / "snowprove.json"
    models.mkdir()
    (models / "dim_users.sql").write_text("SELECT DISTINCT user_id FROM dim_users")
    (models / "schema.yml").write_text(
        """
version: 2
models:
  - name: dim_users
    columns:
      - name: user_id
        tests:
          - unique
"""
    )

    result = CliRunner().invoke(
        main,
        ["dbt", "scan", str(tmp_path), "--format", "json", "--report-file", str(report)],
    )

    assert result.exit_code == 0
    stdout = json.loads(result.stdout)
    file_payload = json.loads(report.read_text())
    assert stdout == file_payload


def test_dbt_scan_cli_reports_diff(tmp_path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    model = models / "dim_users.sql"
    model.write_text("SELECT DISTINCT user_id FROM dim_users")
    (models / "schema.yml").write_text(
        """
version: 2
models:
  - name: dim_users
    columns:
      - name: user_id
        tests:
          - unique
"""
    )

    result = CliRunner().invoke(main, ["dbt", "scan", str(tmp_path), "--diff"])

    assert result.exit_code == 0
    assert f"--- {model}" in result.output
    assert "-SELECT DISTINCT user_id" in result.output
    assert "+SELECT user_id" in result.output


def test_dbt_scan_cli_rejects_diff_json_combination(tmp_path) -> None:
    models = tmp_path / "models"
    models.mkdir()

    result = CliRunner().invoke(
        main,
        ["dbt", "scan", str(tmp_path), "--diff", "--format", "json"],
    )

    assert result.exit_code != 0
    assert "--diff is only supported" in result.output


def test_dbt_scan_cli_can_fail_on_findings(tmp_path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "dim_users.sql").write_text("SELECT DISTINCT user_id FROM dim_users")
    (models / "schema.yml").write_text(
        """
version: 2
models:
  - name: dim_users
    columns:
      - name: user_id
        tests:
          - unique
"""
    )

    result = CliRunner().invoke(main, ["dbt", "scan", str(tmp_path), "--fail-on", "findings"])

    assert result.exit_code == 1
    assert "remove_redundant_distinct" in result.output


def test_dbt_scan_cli_does_not_fail_on_unsupported_with_findings_policy(tmp_path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "orders.sql").write_text(
        "SELECT order_id, {{ cents_to_dollars('subtotal') }} AS subtotal FROM orders"
    )
    (models / "schema.yml").write_text("models: []")

    result = CliRunner().invoke(
        main,
        ["dbt", "scan", str(tmp_path), "--all", "--fail-on", "findings"],
    )

    assert result.exit_code == 0
    assert "UNSUPPORTED" in result.output


def test_dbt_scan_cli_can_scan_compiled_dir(tmp_path) -> None:
    models = tmp_path / "models"
    compiled = tmp_path / "target" / "compiled" / "project" / "models"
    models.mkdir()
    compiled.mkdir(parents=True)
    (models / "dim_users.sql").write_text("SELECT DISTINCT user_id FROM {{ ref('dim_users') }}")
    (compiled / "dim_users.sql").write_text("SELECT DISTINCT user_id FROM dim_users")
    (models / "schema.yml").write_text(
        """
version: 2
models:
  - name: dim_users
    columns:
      - name: user_id
        tests:
          - unique
"""
    )

    result = CliRunner().invoke(
        main,
        ["dbt", "scan", str(tmp_path), "--compiled-dir", str(compiled)],
    )

    assert result.exit_code == 0
    assert "remove_redundant_distinct" in result.output


def test_dbt_scan_cli_can_use_compiled_sql(tmp_path) -> None:
    models = tmp_path / "models"
    compiled = tmp_path / "target" / "compiled" / "project" / "models"
    models.mkdir()
    compiled.mkdir(parents=True)
    (models / "dim_users.sql").write_text("SELECT DISTINCT user_id FROM {{ ref('dim_users') }}")
    (compiled / "dim_users.sql").write_text("SELECT DISTINCT user_id FROM dim_users")
    (models / "schema.yml").write_text(
        """
version: 2
models:
  - name: dim_users
    columns:
      - name: user_id
        tests:
          - unique
"""
    )

    result = CliRunner().invoke(main, ["dbt", "scan", str(tmp_path), "--use-compiled"])

    assert result.exit_code == 0
    assert "remove_redundant_distinct" in result.output
    normalized_output = result.output.replace("\n", "")
    assert str(models / "dim_users.sql") in normalized_output
    assert str(compiled / "dim_users.sql") in normalized_output


def test_dbt_scan_cli_rejects_use_compiled_with_compiled_dir(tmp_path) -> None:
    models = tmp_path / "models"
    compiled = tmp_path / "target" / "compiled" / "project" / "models"
    models.mkdir()
    compiled.mkdir(parents=True)

    result = CliRunner().invoke(
        main,
        [
            "dbt",
            "scan",
            str(tmp_path),
            "--use-compiled",
            "--compiled-dir",
            str(compiled),
        ],
    )

    assert result.exit_code != 0
    assert "cannot be used together" in result.output


def test_dbt_scan_cli_can_write_patches(tmp_path) -> None:
    models = tmp_path / "models"
    patches = tmp_path / "patches"
    models.mkdir()
    (models / "dim_users.sql").write_text("SELECT DISTINCT user_id FROM dim_users")
    (models / "schema.yml").write_text(
        """
version: 2
models:
  - name: dim_users
    columns:
      - name: user_id
        tests:
          - unique
"""
    )

    result = CliRunner().invoke(
        main,
        ["dbt", "scan", str(tmp_path), "--write-patches", str(patches)],
    )

    patch_path = patches / "models" / "dim_users.sql.remove_redundant_distinct.patch"
    assert result.exit_code == 0
    assert "Patch files written: 1" in result.output
    assert patch_path.exists()
    assert "-SELECT DISTINCT user_id" in patch_path.read_text()


def test_dbt_scan_cli_report_file_includes_patch_paths(tmp_path) -> None:
    models = tmp_path / "models"
    patches = tmp_path / "patches"
    report = tmp_path / "snowprove-report.json"
    models.mkdir()
    (models / "dim_users.sql").write_text("SELECT DISTINCT user_id FROM dim_users")
    (models / "schema.yml").write_text(
        """
version: 2
models:
  - name: dim_users
    columns:
      - name: user_id
        tests:
          - unique
"""
    )

    result = CliRunner().invoke(
        main,
        [
            "dbt",
            "scan",
            str(tmp_path),
            "--write-patches",
            str(patches),
            "--report-file",
            str(report),
        ],
    )

    assert result.exit_code == 0
    patch_path = patches / "models" / "dim_users.sql.remove_redundant_distinct.patch"
    payload = json.loads(report.read_text())
    assert payload["results"][0]["patches"] == [
        {
            "path": str(patch_path),
            "rule_name": "remove_redundant_distinct",
        }
    ]


def test_dbt_scan_cli_can_apply_patches(tmp_path) -> None:
    models = tmp_path / "models"
    model = models / "dim_users.sql"
    models.mkdir()
    model.write_text("SELECT DISTINCT user_id FROM dim_users")
    (models / "schema.yml").write_text(
        """
version: 2
models:
  - name: dim_users
    columns:
      - name: user_id
        tests:
          - unique
"""
    )

    result = CliRunner().invoke(
        main,
        ["dbt", "scan", str(tmp_path), "--apply-patches"],
    )

    assert result.exit_code == 0
    assert "Patches applied: 1" in result.output
    assert model.read_text() == "SELECT user_id\nFROM dim_users;\n"


def test_dbt_scan_cli_rejects_write_patches_json_combination(tmp_path) -> None:
    models = tmp_path / "models"
    models.mkdir()

    result = CliRunner().invoke(
        main,
        [
            "dbt",
            "scan",
            str(tmp_path),
            "--write-patches",
            str(tmp_path / "patches"),
            "--format",
            "json",
        ],
    )

    assert result.exit_code != 0
    assert "--write-patches is only supported" in result.output


def test_dbt_scan_cli_rejects_apply_patches_json_combination(tmp_path) -> None:
    models = tmp_path / "models"
    models.mkdir()

    result = CliRunner().invoke(
        main,
        [
            "dbt",
            "scan",
            str(tmp_path),
            "--apply-patches",
            "--format",
            "json",
        ],
    )

    assert result.exit_code != 0
    assert "--apply-patches is only supported" in result.output


def test_dbt_scan_cli_rejects_apply_patches_with_all(tmp_path) -> None:
    models = tmp_path / "models"
    models.mkdir()

    result = CliRunner().invoke(
        main,
        ["dbt", "scan", str(tmp_path), "--apply-patches", "--all"],
    )

    assert result.exit_code != 0
    assert "--apply-patches cannot be used with --all" in result.output


def test_dbt_scan_cli_rejects_apply_and_write_patches_together(tmp_path) -> None:
    models = tmp_path / "models"
    models.mkdir()

    result = CliRunner().invoke(
        main,
        [
            "dbt",
            "scan",
            str(tmp_path),
            "--apply-patches",
            "--write-patches",
            str(tmp_path / "patches"),
        ],
    )

    assert result.exit_code != 0
    assert "--apply-patches and --write-patches cannot be used together" in result.output
