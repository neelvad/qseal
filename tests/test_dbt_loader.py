from pathlib import Path

from snowprove.constraints.dbt_loader import load_dbt_constraints


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
