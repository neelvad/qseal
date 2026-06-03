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
