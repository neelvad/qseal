from pathlib import Path

import pytest

from snowprove.constraints.loader import detect_schema_format, load_constraint_catalog


def test_detects_snowprove_schema_format() -> None:
    assert detect_schema_format({"tables": {}}) == "snowprove"


def test_detects_dbt_schema_format() -> None:
    assert detect_schema_format({"models": []}) == "dbt"


def test_auto_loads_snowprove_constraints(tmp_path: Path) -> None:
    schema = tmp_path / "schema.yml"
    schema.write_text(
        """
tables:
  users:
    unique:
      - [user_id]
"""
    )

    constraints = load_constraint_catalog(schema)

    assert constraints.table("users") is not None
    assert constraints.table("users").has_unique_key(("user_id",))


def test_auto_loads_dbt_constraints(tmp_path: Path) -> None:
    schema = tmp_path / "schema.yml"
    schema.write_text(
        """
version: 2
models:
  - name: users
    columns:
      - name: user_id
        tests:
          - unique
"""
    )

    constraints = load_constraint_catalog(schema)

    assert constraints.table("users") is not None
    assert constraints.table("users").has_unique_key(("user_id",))


def test_auto_rejects_unknown_schema_format(tmp_path: Path) -> None:
    schema = tmp_path / "schema.yml"
    schema.write_text("version: 2\n")

    with pytest.raises(ValueError, match="Could not detect"):
        load_constraint_catalog(schema)
