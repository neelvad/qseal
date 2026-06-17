from pathlib import Path

from qseal.constraints.dbt_loader import load_dbt_constraints


def test_load_dbt_column_unique_and_not_null_tests(tmp_path: Path) -> None:
    schema = tmp_path / "schema.yml"
    schema.write_text(
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

    constraints = load_dbt_constraints(schema)

    dim_users = constraints.table("dim_users")
    assert dim_users is not None
    assert dim_users.has_unique_key(("user_id",))
    assert dim_users.columns["user_id"].nullable is False


def test_load_dbt_dict_style_tests(tmp_path: Path) -> None:
    schema = tmp_path / "schema.yml"
    schema.write_text(
        """
version: 2
models:
  - name: dim_users
    columns:
      - name: user_id
        tests:
          - unique:
              config:
                severity: error
          - not_null:
              config:
                severity: error
"""
    )

    constraints = load_dbt_constraints(schema)

    dim_users = constraints.table("dim_users")
    assert dim_users is not None
    assert dim_users.has_unique_key(("user_id",))
    assert dim_users.columns["user_id"].nullable is False


def test_load_dbt_relationships_tests_as_foreign_keys(tmp_path: Path) -> None:
    schema = tmp_path / "schema.yml"
    schema.write_text(
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

    constraints = load_dbt_constraints(schema)

    fact_orders = constraints.table("fact_orders")
    assert fact_orders is not None
    assert fact_orders.is_non_null("user_id")
    assert fact_orders.has_foreign_key(
        ("user_id",),
        ref_table="dim_users",
        ref_columns=("user_id",),
    )


def test_load_dbt_relationships_tests_with_arguments_block(tmp_path: Path) -> None:
    schema = tmp_path / "schema.yml"
    schema.write_text(
        """
version: 2
models:
  - name: fact_orders
    columns:
      - name: customer_id
        tests:
          - relationships:
              arguments:
                to: "{{ source('crm', 'customers') }}"
                field: id
"""
    )

    constraints = load_dbt_constraints(schema)

    fact_orders = constraints.table("fact_orders")
    assert fact_orders is not None
    assert fact_orders.has_foreign_key(
        ("customer_id",),
        ref_table="customers",
        ref_columns=("id",),
    )


def test_load_dbt_source_table_tests(tmp_path: Path) -> None:
    schema = tmp_path / "schema.yml"
    schema.write_text(
        """
version: 2
sources:
  - name: crm
    tables:
      - name: customers
        columns:
          - name: id
            tests:
              - unique
              - not_null
"""
    )

    constraints = load_dbt_constraints(schema)

    customers = constraints.table("customers")
    assert customers is not None
    assert customers.has_unique_key(("id",))
    assert customers.is_non_null("id")


def test_load_dbt_utils_unique_combination_tests(tmp_path: Path) -> None:
    schema = tmp_path / "schema.yml"
    schema.write_text(
        """
version: 2
models:
  - name: fact_orders
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

    constraints = load_dbt_constraints(schema)

    fact_orders = constraints.table("fact_orders")
    assert fact_orders is not None
    assert fact_orders.has_unique_key(("tenant_id", "order_id"))
    assert fact_orders.has_non_null_unique_key(("tenant_id", "order_id"))


def test_load_unique_combination_tests_from_data_tests_arguments_block(
    tmp_path: Path,
) -> None:
    schema = tmp_path / "schema.yml"
    schema.write_text(
        """
version: 2
sources:
  - name: raw
    tables:
      - name: events
        data_tests:
          - unique_combination_of_columns:
              arguments:
                combination_of_columns:
                  - tenant_id
                  - natural_key
        columns:
          - name: tenant_id
            data_tests:
              - not_null
          - name: natural_key
            data_tests:
              - not_null
"""
    )

    constraints = load_dbt_constraints(schema)

    events = constraints.table("events")
    assert events is not None
    assert events.has_unique_key(("tenant_id", "natural_key"))
    assert events.has_non_null_unique_key(("tenant_id", "natural_key"))
