from click.testing import CliRunner

from snowprove.cli import main


def test_suggest_cli(tmp_path) -> None:
    query = tmp_path / "query.sql"
    schema = tmp_path / "schema.yml"
    query.write_text("SELECT DISTINCT user_id FROM users")
    schema.write_text(
        """
tables:
  users:
    unique:
      - [user_id]
"""
    )

    result = CliRunner().invoke(main, ["suggest", str(query), "--schema", str(schema)])

    assert result.exit_code == 0
    assert "PROVEN_EQUIVALENT" in result.output
    assert "SELECT user_id" in result.output
