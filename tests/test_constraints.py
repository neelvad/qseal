from pathlib import Path

from snowprove.constraints.yaml_loader import load_constraints


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
