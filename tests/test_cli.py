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
    assert "Only LEFT JOIN is supported" in result.output


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


def test_suggest_cli_reports_predicate_pushdown(tmp_path) -> None:
    query = tmp_path / "query.sql"
    schema = tmp_path / "schema.yml"
    query.write_text(
        """
        SELECT user_id, revenue
        FROM (
          SELECT user_id, revenue
          FROM orders
        ) x
        WHERE revenue > 0
        """
    )
    schema.write_text("tables: {}\n")

    result = CliRunner().invoke(main, ["suggest", str(query), "--schema", str(schema)])

    assert result.exit_code == 0
    assert "predicate_pushdown" in result.output
    assert "SELECT user_id, revenue" in result.output


def test_suggest_cli_reports_join_elimination(tmp_path) -> None:
    query = tmp_path / "query.sql"
    schema = tmp_path / "schema.yml"
    query.write_text(
        """
        SELECT f.user_id, f.revenue
        FROM fact_orders f
        LEFT JOIN dim_users u ON f.user_id = u.user_id
        """
    )
    schema.write_text(
        """
tables:
  dim_users:
    unique:
      - [user_id]
"""
    )

    result = CliRunner().invoke(main, ["suggest", str(query), "--schema", str(schema)])

    assert result.exit_code == 0
    assert "remove_unused_left_join" in result.output
    assert "FROM fact_orders f" in result.output


def test_suggest_cli_can_report_all_applicable_results(tmp_path) -> None:
    query = tmp_path / "query.sql"
    schema = tmp_path / "schema.yml"
    query.write_text(
        """
        SELECT DISTINCT user_id
        FROM (
          SELECT user_id
          FROM users
        ) x
        WHERE user_id = 1
        """
    )
    schema.write_text("tables: {}\n")

    result = CliRunner().invoke(main, ["suggest", str(query), "--schema", str(schema), "--all"])

    assert result.exit_code == 0
    assert "remove_redundant_distinct" in result.output
    assert "predicate_pushdown" in result.output
