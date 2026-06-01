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


def test_check_cli(tmp_path) -> None:
    original = tmp_path / "original.sql"
    rewritten = tmp_path / "rewritten.sql"
    schema = tmp_path / "schema.yml"
    original.write_text("SELECT DISTINCT user_id FROM users")
    rewritten.write_text("SELECT user_id FROM users")
    schema.write_text(
        """
tables:
  users:
    unique:
      - [user_id]
"""
    )

    result = CliRunner().invoke(
        main,
        ["check", str(original), str(rewritten), "--schema", str(schema)],
    )

    assert result.exit_code == 0
    assert "PROVEN_EQUIVALENT" in result.output


def test_suggest_cli_reports_unsupported_sql(tmp_path) -> None:
    query = tmp_path / "query.sql"
    schema = tmp_path / "schema.yml"
    query.write_text("SELECT user_id FROM users JOIN orders USING (user_id)")
    schema.write_text("tables: {}\n")

    result = CliRunner().invoke(main, ["suggest", str(query), "--schema", str(schema)])

    assert result.exit_code == 0
    assert "UNSUPPORTED" in result.output
    assert "Joins are not supported" in result.output


def test_check_cli_reports_unsupported_original_sql(tmp_path) -> None:
    original = tmp_path / "original.sql"
    rewritten = tmp_path / "rewritten.sql"
    schema = tmp_path / "schema.yml"
    original.write_text("SELECT user_id FROM users JOIN orders USING (user_id)")
    rewritten.write_text("SELECT user_id FROM users")
    schema.write_text("tables: {}\n")

    result = CliRunner().invoke(
        main,
        ["check", str(original), str(rewritten), "--schema", str(schema)],
    )

    assert result.exit_code == 0
    assert "UNSUPPORTED" in result.output
    assert "Original query unsupported" in result.output
