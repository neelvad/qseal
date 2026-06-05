from pathlib import Path

from snowprove.dbt.project import discover_compiled_sql_path
from snowprove.dbt.scan import scan_dbt_project
from snowprove.rewrites.base import VerificationStatus
from snowprove.rewrites.registry import DEFAULT_RULES

FIXTURES = Path(__file__).parent / "fixtures"


def test_scan_dbt_project_returns_proven_findings(tmp_path: Path) -> None:
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

    result = scan_dbt_project(tmp_path, rules=DEFAULT_RULES)

    assert result.model_count == 1
    assert result.has_proven_findings()
    assert result.proven_finding_count() == 1
    assert result.status_counts() == {"PROVEN_EQUIVALENT": 1}
    assert result.rule_counts() == {"remove_redundant_distinct": 1}
    assert len(result.results) == 1
    assert result.results[0].path == models / "dim_users.sql"
    assert result.results[0].scanned_path == models / "dim_users.sql"
    assert result.results[0].source_path == models / "dim_users.sql"
    assert result.results[0].suggestions[0].status == VerificationStatus.PROVEN_EQUIVALENT


def test_scan_dbt_project_matches_constraints_for_qualified_relations(tmp_path: Path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "dim_users.sql").write_text(
        "SELECT DISTINCT user_id FROM analytics.public.dim_users"
    )
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

    result = scan_dbt_project(tmp_path, rules=DEFAULT_RULES)

    suggestion = result.results[0].suggestions[0]
    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rewritten_sql == "SELECT user_id\nFROM analytics.public.dim_users;"


def test_scan_dbt_project_skips_jinja_by_default(tmp_path: Path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "orders.sql").write_text("SELECT order_id FROM {{ ref('orders') }}")
    (models / "schema.yml").write_text("models: []")

    result = scan_dbt_project(tmp_path, rules=DEFAULT_RULES)

    assert result.model_count == 1
    assert not result.has_proven_findings()
    assert result.summary()["proven_finding_count"] == 0
    assert result.results == ()


def test_scan_dbt_project_can_include_unsupported_jinja(tmp_path: Path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "orders.sql").write_text(
        "SELECT order_id, {{ cents_to_dollars('subtotal') }} AS subtotal FROM orders"
    )
    (models / "schema.yml").write_text("models: []")

    result = scan_dbt_project(tmp_path, rules=DEFAULT_RULES, include_all=True)

    assert result.model_count == 1
    assert not result.has_proven_findings()
    assert result.status_counts() == {"UNSUPPORTED": 1}
    assert result.rule_counts() == {"dbt_scan": 1}
    reason = (
        "Model contains unsupported dbt/Jinja expression 'cents_to_dollars'; "
        "compile before scanning."
    )
    assert result.reason_counts() == {
        reason: 1
    }
    assert result.summary()["reason_counts"] == {
        reason: 1
    }
    assert result.results[0].suggestions[0].status == VerificationStatus.UNSUPPORTED


def test_scan_dbt_project_preprocesses_static_ref_calls(tmp_path: Path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "dim_users.sql").write_text("SELECT DISTINCT user_id FROM {{ ref('dim_users') }}")
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

    result = scan_dbt_project(tmp_path, rules=DEFAULT_RULES)

    assert result.has_proven_findings()
    assert result.results[0].source_sql_preprocessed is True
    assert result.results[0].apply_ready() is False
    assert "normalized before verification" in str(result.results[0].apply_blocker())
    assert result.results[0].suggestions[0].rewritten_sql == "SELECT user_id\nFROM dim_users;"


def test_scan_dbt_project_preprocesses_static_source_calls(tmp_path: Path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "raw_customers.sql").write_text(
        "SELECT DISTINCT customer_id FROM {{ source('ecom', 'raw_customers') }}"
    )
    (models / "schema.yml").write_text(
        """
version: 2
models:
  - name: raw_customers
    columns:
      - name: customer_id
        tests:
          - unique
"""
    )

    result = scan_dbt_project(tmp_path, rules=DEFAULT_RULES)

    assert result.has_proven_findings()
    assert result.results[0].source_sql_preprocessed is True
    assert result.results[0].suggestions[0].rewritten_sql == (
        "SELECT customer_id\nFROM ecom.raw_customers;"
    )


def test_scan_dbt_project_ignores_dbt_config_calls(tmp_path: Path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "dim_users.sql").write_text(
        """
        {{ config(materialized='view') }}

        SELECT DISTINCT user_id
        FROM {{ ref('dim_users') }}
        """
    )
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

    result = scan_dbt_project(tmp_path, rules=DEFAULT_RULES)

    assert result.has_proven_findings()
    assert result.results[0].source_sql_preprocessed is True
    assert result.results[0].apply_ready() is False
    assert result.results[0].suggestions[0].rewritten_sql == "SELECT user_id\nFROM dim_users;"


def test_scan_dbt_project_parses_simple_cte_chain(tmp_path: Path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "dim_users.sql").write_text(
        """
        WITH source AS (
          SELECT * FROM {{ source('ecom', 'raw_users') }}
        )
        SELECT DISTINCT user_id FROM source
        """
    )
    (models / "schema.yml").write_text(
        """
version: 2
models:
  - name: raw_users
    columns:
      - name: user_id
        tests:
          - unique
"""
    )

    result = scan_dbt_project(tmp_path, rules=DEFAULT_RULES)

    assert result.has_proven_findings()
    assert result.results[0].source_sql_preprocessed is True
    assert result.results[0].apply_ready() is False
    assert "normalized before verification" in str(result.results[0].apply_blocker())


def test_scan_dbt_project_can_scan_compiled_sql(tmp_path: Path) -> None:
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

    result = scan_dbt_project(tmp_path, rules=DEFAULT_RULES, compiled_path=compiled)

    assert result.model_count == 1
    assert result.has_proven_findings()
    assert result.results[0].scanned_path == compiled / "dim_users.sql"
    assert result.results[0].source_path == models / "dim_users.sql"
    assert result.results[0].apply_ready() is False
    assert "compiled SQL" in str(result.results[0].apply_blocker())


def test_scan_dbt_project_maps_compiled_project_root_to_source_models(tmp_path: Path) -> None:
    models = tmp_path / "models"
    compiled_root = tmp_path / "target" / "compiled" / "project"
    compiled_models = compiled_root / "models"
    models.mkdir()
    compiled_models.mkdir(parents=True)
    (models / "dim_users.sql").write_text("SELECT DISTINCT user_id FROM {{ ref('dim_users') }}")
    (compiled_models / "dim_users.sql").write_text("SELECT DISTINCT user_id FROM dim_users")
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

    result = scan_dbt_project(tmp_path, rules=DEFAULT_RULES, compiled_path=compiled_root)

    assert result.results[0].scanned_path == compiled_models / "dim_users.sql"
    assert result.results[0].source_path == models / "dim_users.sql"


def test_scan_dbt_project_marks_package_compiled_sql_not_apply_ready(tmp_path: Path) -> None:
    models = tmp_path / "models"
    compiled_root = tmp_path / "target" / "compiled"
    package_models = compiled_root / "dbt_utils" / "models"
    models.mkdir()
    package_models.mkdir(parents=True)
    (models / "schema.yml").write_text(
        """
version: 2
models:
  - name: helper
    columns:
      - name: helper_id
        tests:
          - unique
"""
    )
    (package_models / "helper.sql").write_text("SELECT DISTINCT helper_id FROM helper")

    result = scan_dbt_project(tmp_path, rules=DEFAULT_RULES, compiled_path=compiled_root)

    assert result.results[0].source_path is None
    assert result.results[0].apply_ready() is False
    assert result.results[0].apply_blocker() == "No matching source model file."


def test_scan_jaffle_like_fixture_reports_stable_counts() -> None:
    project = FIXTURES / "dbt_projects" / "jaffle_like"

    result = scan_dbt_project(project, rules=DEFAULT_RULES, include_all=True)

    assert result.model_count == 5
    assert result.proven_finding_count() == 1
    assert result.status_counts() == {
        "PROVEN_EQUIVALENT": 1,
        "UNSUPPORTED": 1,
    }
    assert result.reason_counts() == {
        (
            "Model contains unsupported dbt/Jinja expression 'cents_to_dollars'; "
            "compile before scanning."
        ): 1,
    }


def test_scan_synthetic_duckdb_fixture_reports_raw_blockers() -> None:
    project = FIXTURES / "dbt_projects" / "synthetic_duckdb"

    result = scan_dbt_project(project, rules=DEFAULT_RULES, include_all=True)

    assert result.model_count == 5
    assert result.proven_finding_count() == 1
    assert result.status_counts() == {
        "UNKNOWN": 1,
        "PROVEN_EQUIVALENT": 1,
        "UNSUPPORTED": 1,
    }
    assert result.rule_counts() == {
        "dbt_scan": 1,
        "remove_unused_left_join": 1,
        "remove_redundant_distinct": 1,
    }
    assert result.reason_counts() == {
        "orders.customer_id is not known to be unique.": 1,
        "Model contains unsupported dbt/Jinja block syntax; compile before scanning.": 1,
    }


def test_scan_synthetic_duckdb_fixture_reports_compiled_blockers() -> None:
    project = FIXTURES / "dbt_projects" / "synthetic_duckdb"
    compiled_path = discover_compiled_sql_path(project)

    result = scan_dbt_project(
        project,
        rules=DEFAULT_RULES,
        include_all=True,
        compiled_path=compiled_path,
    )

    assert result.model_count == 5
    assert result.proven_finding_count() == 1
    assert result.status_counts() == {
        "UNKNOWN": 1,
        "PROVEN_EQUIVALENT": 1,
    }
    assert result.reason_counts() == {
        "orders.customer_id is not known to be unique.": 1,
    }

    dim_users = next(
        scan_result
        for scan_result in result.results
        if scan_result.source_path == project / "models" / "dim_users.sql"
    )
    assert dim_users.scanned_path == compiled_path / "dim_users.sql"
    assert dim_users.source_sql_preprocessed is False
    assert dim_users.apply_ready() is False
    assert (
        dim_users.apply_blocker()
        == "Scanned compiled SQL; source file was not verified directly."
    )
