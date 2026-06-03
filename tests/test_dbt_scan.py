from pathlib import Path

from snowprove.dbt.scan import scan_dbt_project
from snowprove.rewrites.base import VerificationStatus
from snowprove.rewrites.registry import DEFAULT_RULES


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
    (models / "orders.sql").write_text("SELECT order_id FROM {{ ref('orders') }}")
    (models / "schema.yml").write_text("models: []")

    result = scan_dbt_project(tmp_path, rules=DEFAULT_RULES, include_all=True)

    assert result.model_count == 1
    assert not result.has_proven_findings()
    assert result.status_counts() == {"UNSUPPORTED": 1}
    assert result.rule_counts() == {"dbt_scan": 1}
    assert result.results[0].suggestions[0].status == VerificationStatus.UNSUPPORTED


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
