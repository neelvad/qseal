import json
from pathlib import Path

from click.testing import CliRunner

from qseal.cli import main
from qseal.dbt.intake import build_dbt_intake_report
from qseal.dbt.scan import scan_dbt_project
from qseal.rewrites.registry import DEFAULT_RULES

FIXTURES = Path(__file__).parent / "fixtures"


def test_dbt_intake_report_is_aggregate_only_for_yield_pack() -> None:
    project = FIXTURES / "dbt_projects" / "yield_pack"

    scan = scan_dbt_project(project, rules=DEFAULT_RULES, include_all=True)
    report = build_dbt_intake_report(
        scan,
        rules=DEFAULT_RULES,
        include_all=True,
        compiled_sql=False,
        use_compiled_auto=False,
        chain=False,
        max_chain_steps=8,
    )
    payload = json.dumps(report, sort_keys=True)

    assert report["artifact_type"] == "dbt_intake"
    assert report["redaction"] == {
        "contains_diffs": False,
        "contains_file_paths": False,
        "contains_literal_values": False,
        "contains_model_names": False,
        "contains_raw_reasons": False,
        "contains_sql": False,
        "level": "aggregate_only",
    }
    assert report["summary"]["model_count"] == 12
    assert report["summary"]["proven_finding_count"] == 13
    assert report["summary"]["required_test_category_counts"]["accepted_values"] == 2
    assert report["summary"]["required_test_category_counts"]["relationships"] == 1
    assert report["summary"]["required_test_category_counts"]["unique"] >= 1
    assert report["summary"]["required_test_category_counts"]["not_null"] >= 1
    assert str(project) not in payload
    assert "orders_distinct_chain.sql" not in payload
    assert "stg_orders" not in payload
    assert "SELECT" not in payload.upper()


def test_dbt_intake_report_redacts_raw_unsupported_reasons(tmp_path: Path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "secret_orders.sql").write_text(
        "SELECT {{ secret_macro('secret_column') }} AS amount FROM secret_orders"
    )
    (models / "schema.yml").write_text("models: []")

    scan = scan_dbt_project(tmp_path, rules=DEFAULT_RULES, include_all=True)
    report = build_dbt_intake_report(
        scan,
        rules=DEFAULT_RULES,
        include_all=True,
        compiled_sql=False,
        use_compiled_auto=False,
        chain=False,
        max_chain_steps=8,
    )
    payload = json.dumps(report, sort_keys=True)

    assert report["summary"]["reason_category_counts"] == {"dbt_jinja_expression": 1}
    assert "secret_macro" not in payload
    assert "secret_column" not in payload
    assert "secret_orders" not in payload
    assert str(tmp_path) not in payload


def test_dbt_intake_cli_reports_json_without_sql_or_paths(tmp_path: Path) -> None:
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
          - not_null
"""
    )

    result = CliRunner().invoke(main, ["dbt", "intake", str(tmp_path), "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["artifact_type"] == "dbt_intake"
    assert payload["summary"]["model_count"] == 1
    assert payload["summary"]["proven_finding_count"] == 1
    assert payload["summary"]["rule_counts"] == {"remove_redundant_distinct": 1}
    assert "dim_users.sql" not in result.output
    assert "SELECT DISTINCT" not in result.output
    assert str(tmp_path) not in result.output


def test_dbt_intake_cli_writes_report_file(tmp_path: Path) -> None:
    models = tmp_path / "models"
    report_path = tmp_path / "artifacts" / "qseal-intake.json"
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
          - not_null
"""
    )

    result = CliRunner().invoke(
        main,
        ["dbt", "intake", str(tmp_path), "--report-file", str(report_path)],
    )

    assert result.exit_code == 0
    assert "Intake report file written:" in result.output
    payload = json.loads(report_path.read_text())
    assert payload["artifact_type"] == "dbt_intake"
    assert payload["summary"]["proven_finding_count"] == 1
