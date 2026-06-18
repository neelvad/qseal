from pathlib import Path

from qseal.dbt.project import discover_compiled_sql_path
from qseal.dbt.scan import scan_dbt_project
from qseal.report.guards import required_guarding_tests
from qseal.rewrites.base import VerificationStatus
from qseal.rewrites.registry import DEFAULT_RULES

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
          - not_null
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


def test_scan_dbt_project_uses_unique_combination_for_distinct(
    tmp_path: Path,
) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "orders.sql").write_text(
        "SELECT DISTINCT tenant_id, order_id, status FROM orders"
    )
    (models / "schema.yml").write_text(
        """
version: 2
models:
  - name: orders
    tests:
      - dbt_utils.unique_combination_of_columns:
          combination_of_columns:
            - tenant_id
            - order_id
    columns:
      - name: tenant_id
        tests:
          - not_null
      - name: order_id
        tests:
          - not_null
"""
    )

    result = scan_dbt_project(tmp_path, rules=DEFAULT_RULES)

    assert result.proven_finding_count() == 1
    suggestion = result.results[0].suggestions[0]
    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rule_name == "remove_redundant_distinct"
    assert required_guarding_tests(suggestion) == (
        "dbt test: unique combination on orders(tenant_id, order_id)",
        "dbt test: not_null on orders.tenant_id",
        "dbt test: not_null on orders.order_id",
    )
    assert suggestion.rewritten_sql == "SELECT tenant_id, order_id, status\nFROM orders;"


def test_scan_dbt_project_rewrites_count_distinct(
    tmp_path: Path,
) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "users.sql").write_text(
        "SELECT COUNT(DISTINCT user_id) AS unique_users FROM users"
    )
    (models / "schema.yml").write_text(
        """
version: 2
models:
  - name: users
    columns:
      - name: user_id
        tests:
          - unique
          - not_null
"""
    )

    result = scan_dbt_project(tmp_path, rules=DEFAULT_RULES)

    assert result.proven_finding_count() == 1
    suggestion = result.results[0].suggestions[0]
    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rule_name == "remove_redundant_count_distinct"
    assert required_guarding_tests(suggestion) == (
        "dbt test: unique on users.user_id",
        "dbt test: not_null on users.user_id",
    )
    assert suggestion.rewritten_sql == "SELECT COUNT(user_id) AS unique_users\nFROM users;"


def test_scan_dbt_project_removes_redundant_accepted_values_filter(
    tmp_path: Path,
) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "orders.sql").write_text(
        "SELECT order_id FROM orders WHERE status IN ('placed', 'shipped')"
    )
    (models / "schema.yml").write_text(
        """
version: 2
models:
  - name: orders
    columns:
      - name: status
        tests:
          - not_null
          - accepted_values:
              values:
                - placed
                - shipped
"""
    )

    result = scan_dbt_project(tmp_path, rules=DEFAULT_RULES)

    assert result.proven_finding_count() == 1
    suggestion = result.results[0].suggestions[0]
    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rule_name == "remove_redundant_accepted_values_filter"
    assert required_guarding_tests(suggestion) == (
        "dbt test: accepted_values on orders.status in ('placed', 'shipped')",
        "dbt test: not_null on orders.status",
    )
    assert suggestion.rewritten_sql == "SELECT order_id\nFROM orders;"


def test_scan_dbt_project_simplifies_accepted_values_case(
    tmp_path: Path,
) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "orders.sql").write_text(
        """
SELECT
  CASE
    WHEN status = 'cancelled' THEN 'bad'
    ELSE 'ok'
  END AS status_group
FROM orders
"""
    )
    (models / "schema.yml").write_text(
        """
version: 2
models:
  - name: orders
    columns:
      - name: status
        tests:
          - not_null
          - accepted_values:
              values:
                - placed
                - shipped
"""
    )

    result = scan_dbt_project(tmp_path, rules=DEFAULT_RULES)

    assert result.proven_finding_count() == 1
    suggestion = result.results[0].suggestions[0]
    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rule_name == "simplify_accepted_values_case"
    assert required_guarding_tests(suggestion) == (
        "dbt test: accepted_values on orders.status in ('placed', 'shipped')",
        "dbt test: not_null on orders.status",
    )
    assert suggestion.rewritten_sql == "SELECT 'ok' AS status_group\nFROM orders;"


def test_scan_dbt_project_merges_accepted_values_and_not_null(
    tmp_path: Path,
) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "orders.sql").write_text(
        "SELECT order_id FROM orders WHERE status IN ('placed', 'shipped')"
    )
    (models / "not_null.yml").write_text(
        """
version: 2
models:
  - name: orders
    columns:
      - name: status
        tests:
          - not_null
"""
    )
    (models / "accepted_values.yml").write_text(
        """
version: 2
models:
  - name: orders
    columns:
      - name: status
        tests:
          - accepted_values:
              values:
                - placed
                - shipped
"""
    )

    result = scan_dbt_project(tmp_path, rules=DEFAULT_RULES)

    assert result.proven_finding_count() == 1
    assert result.results[0].suggestions[0].rule_name == (
        "remove_redundant_accepted_values_filter"
    )


def test_scan_dbt_project_uses_relationships_for_inner_join_elimination(
    tmp_path: Path,
) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "fct_orders.sql").write_text(
        """
SELECT orders.order_id, orders.user_id
FROM fact_orders AS orders
INNER JOIN dim_users AS users ON orders.user_id = users.user_id
"""
    )
    (models / "schema.yml").write_text(
        """
version: 2
models:
  - name: fact_orders
    columns:
      - name: user_id
        tests:
          - not_null
          - relationships:
              to: ref('dim_users')
              field: user_id
  - name: dim_users
    columns:
      - name: user_id
        tests:
          - unique
"""
    )

    result = scan_dbt_project(tmp_path, rules=DEFAULT_RULES)

    assert result.proven_finding_count() == 1
    suggestion = result.results[0].suggestions[0]
    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rule_name == "remove_foreign_key_inner_join"
    assert required_guarding_tests(suggestion) == (
        "dbt test: relationships from fact_orders.user_id to dim_users.user_id",
        "dbt test: not_null on fact_orders.user_id",
        "dbt test: unique on dim_users.user_id",
    )
    assert "INNER JOIN" not in suggestion.rewritten_sql


def test_scan_dbt_project_uses_composite_unique_key_for_left_join_elimination(
    tmp_path: Path,
) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "fct_orders.sql").write_text(
        """
SELECT orders.order_id, orders.user_id
FROM fact_orders AS orders
LEFT JOIN dim_users AS users
  ON orders.tenant_id = users.tenant_id AND orders.user_id = users.user_id
"""
    )
    (models / "schema.yml").write_text(
        """
version: 2
models:
  - name: dim_users
    tests:
      - dbt_utils.unique_combination_of_columns:
          combination_of_columns:
            - tenant_id
            - user_id
"""
    )

    result = scan_dbt_project(tmp_path, rules=DEFAULT_RULES)

    assert result.proven_finding_count() == 1
    suggestion = result.results[0].suggestions[0]
    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rule_name == "remove_unused_left_join"
    assert required_guarding_tests(suggestion) == (
        "dbt test: unique combination on dim_users(tenant_id, user_id)",
    )
    assert "LEFT JOIN" not in suggestion.rewritten_sql


def test_scan_dbt_project_merges_source_relationship_premises(
    tmp_path: Path,
) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "fct_orders.sql").write_text(
        """
SELECT orders.order_id, orders.customer_id
FROM fact_orders AS orders
INNER JOIN {{ source('crm', 'customers') }} AS customers
  ON orders.customer_id = customers.id
"""
    )
    (models / "fact_orders.yml").write_text(
        """
version: 2
models:
  - name: fact_orders
    columns:
      - name: customer_id
        tests:
          - not_null
"""
    )
    (models / "relationships.yml").write_text(
        """
version: 2
models:
  - name: fact_orders
    columns:
      - name: customer_id
        tests:
          - relationships:
              to: "{{ source('crm', 'customers') }}"
              field: id
sources:
  - name: crm
    tables:
      - name: customers
        columns:
          - name: id
            tests:
              - unique
"""
    )

    result = scan_dbt_project(tmp_path, rules=DEFAULT_RULES)

    assert result.proven_finding_count() == 1
    suggestion = result.results[0].suggestions[0]
    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rule_name == "remove_foreign_key_inner_join"
    assert required_guarding_tests(suggestion) == (
        "dbt test: relationships from fact_orders.customer_id to customers.id",
        "dbt test: not_null on fact_orders.customer_id",
        "dbt test: unique on customers.id",
    )


def test_scan_dbt_project_finds_subtree_rewrites_in_unsupported_models(tmp_path: Path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "user_orders.sql").write_text(
        """
with active_users as (
    select distinct user_id from stg_users
),
user_orders as (
    select active_users.user_id, count(order_id) as order_count
    from orders
    left join active_users on orders.user_id = active_users.user_id
    group by active_users.user_id
)
select * from user_orders
"""
    )
    (models / "schema.yml").write_text(
        """
version: 2
models:
  - name: stg_users
    columns:
      - name: user_id
        tests:
          - unique
          - not_null
"""
    )

    result = scan_dbt_project(tmp_path, rules=DEFAULT_RULES)

    assert result.proven_finding_count() == 1
    suggestion = result.results[0].suggestions[0]
    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rule_name == "remove_redundant_distinct"
    assert "CTE 'active_users'" in suggestion.reason
    assert "GROUP BY" in suggestion.rewritten_sql.upper()


def test_scan_dbt_project_records_explicit_duckdb_dialect(tmp_path: Path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "users.sql").write_text("SELECT user_id FROM users")
    (models / "schema.yml").write_text("models: []\n")

    result = scan_dbt_project(
        tmp_path,
        rules=DEFAULT_RULES,
        include_all=True,
        dialect="duckdb",
    )

    assert result.dialect == "duckdb"


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
          - not_null
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
          - not_null
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
          - not_null
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
          - not_null
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
          - not_null
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
    compiled_tests = compiled / "schema.yml"
    models.mkdir()
    compiled.mkdir(parents=True)
    compiled_tests.mkdir()
    (models / "dim_users.sql").write_text("SELECT DISTINCT user_id FROM {{ ref('dim_users') }}")
    (compiled / "dim_users.sql").write_text("SELECT DISTINCT user_id FROM dim_users")
    (compiled_tests / "unique_dim_users_user_id.sql").write_text(
        "SELECT user_id FROM dim_users GROUP BY user_id HAVING COUNT(*) > 1"
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
          - not_null
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
          - not_null
"""
    )

    result = scan_dbt_project(tmp_path, rules=DEFAULT_RULES, compiled_path=compiled_root)

    assert result.results[0].scanned_path == compiled_models / "dim_users.sql"
    assert result.results[0].source_path == models / "dim_users.sql"


def test_scan_dbt_project_skips_package_compiled_sql_without_source_model(
    tmp_path: Path,
) -> None:
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
          - not_null
"""
    )
    (package_models / "helper.sql").write_text("SELECT DISTINCT helper_id FROM helper")

    result = scan_dbt_project(tmp_path, rules=DEFAULT_RULES, compiled_path=compiled_root)

    assert result.model_count == 0
    assert result.results == ()


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

    assert result.model_count == 9
    assert result.proven_finding_count() == 1
    assert result.status_counts() == {
        "UNKNOWN": 1,
        "PROVEN_EQUIVALENT": 1,
    }
    assert result.rule_counts() == {
        "remove_unused_left_join": 1,
        "remove_redundant_distinct": 1,
    }
    assert result.reason_counts() == {
        (
            "The query references a CTE relation, so a standalone rewritten query "
            "cannot be generated."
        ): 1,
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

    assert result.model_count == 9
    assert result.proven_finding_count() == 1
    assert result.status_counts() == {
        "UNKNOWN": 1,
        "PROVEN_EQUIVALENT": 1,
    }
    assert result.reason_counts() == {
        (
            "The query references a CTE relation, so a standalone rewritten query "
            "cannot be generated."
        ): 1,
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


def test_scan_dbt_project_finds_subtree_rewrites_behind_opaque_cte_outer_query(
    tmp_path: Path,
) -> None:
    # The outer query parses (opaque CTE source), but the redundant filter is
    # only visible inside the CTE body, which the fragment path scans.
    models = tmp_path / "models"
    models.mkdir()
    (models / "recent_events.sql").write_text(
        """
with recent as (
    select user_id, ts from events where user_id is not null
)
select recent.user_id from recent where recent.ts > 1
"""
    )
    (models / "schema.yml").write_text(
        """
version: 2
models:
  - name: events
    columns:
      - name: user_id
        tests:
          - not_null
"""
    )

    result = scan_dbt_project(tmp_path, rules=DEFAULT_RULES)

    assert result.proven_finding_count() == 1
    suggestion = result.results[0].suggestions[0]
    assert suggestion.rule_name == "remove_redundant_not_null_filter"
    assert "CTE 'recent'" in suggestion.reason
    assert "IS NOT NULL" not in suggestion.rewritten_sql.upper()
    assert "WITH recent AS" in suggestion.rewritten_sql
