from pathlib import Path

from qseal.constraints.model import ColumnConstraint, TableConstraints
from qseal.constraints.yaml_loader import load_constraints


def test_load_constraints(tmp_path: Path) -> None:
    schema = tmp_path / "schema.yml"
    schema.write_text(
        """
tables:
  users:
    columns:
      user_id:
        nullable: false
    unique:
      - [user_id]
"""
    )

    constraints = load_constraints(schema)

    users = constraints.table("users")
    assert users is not None
    assert users.has_unique_key(("user_id",))


def test_finds_contained_composite_unique_key() -> None:
    table = TableConstraints(
        columns={
            "tenant_id": ColumnConstraint(nullable=False),
            "order_id": ColumnConstraint(nullable=False),
            "status": ColumnConstraint(nullable=True),
        },
        unique=[("tenant_id", "order_id")],
    )

    assert table.unique_key_contained_in(("tenant_id", "order_id", "status")) == (
        "tenant_id",
        "order_id",
    )
    assert table.non_null_unique_key_contained_in(
        ("tenant_id", "order_id", "status")
    ) == (
        "tenant_id",
        "order_id",
    )


def test_rejects_nullable_composite_unique_key_for_non_null_lookup() -> None:
    table = TableConstraints(
        columns={
            "tenant_id": ColumnConstraint(nullable=False),
            "order_id": ColumnConstraint(nullable=True),
        },
        unique=[("tenant_id", "order_id")],
    )

    assert table.has_unique_key(("tenant_id", "order_id"))
    assert table.non_null_unique_key_contained_in(("tenant_id", "order_id")) is None
