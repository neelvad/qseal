from pathlib import Path

from snowprove.dbt.scan import scan_dbt_project
from snowprove.report.markdown import COMMENT_MARKER, render_dbt_scan_markdown
from snowprove.rewrites.registry import DEFAULT_RULES


def _project(tmp_path: Path, model_sql: str) -> Path:
    models = tmp_path / "models"
    models.mkdir()
    (models / "schema.yml").write_text(
        "version: 2\nmodels:\n  - name: dim_users\n"
        "    columns: [{name: user_id, tests: [unique, not_null]}]\n"
    )
    (models / "dim_users.sql").write_text(model_sql)
    return tmp_path


def test_markdown_renders_finding_with_guards_and_diff(tmp_path: Path) -> None:
    project = _project(tmp_path, "SELECT DISTINCT user_id FROM dim_users")
    result = scan_dbt_project(project, rules=DEFAULT_RULES)

    md = render_dbt_scan_markdown(result)

    assert md.startswith(COMMENT_MARKER)
    assert "Found **1** proven-equivalent rewrite" in md
    assert "`remove_redundant_distinct`" in md
    assert "dbt test: unique on dim_users.user_id" in md
    assert "dbt test: not_null on dim_users.user_id" in md
    assert "```diff" in md
    # path is repo-relative, not an absolute temp path
    assert "### `models/dim_users.sql`" in md
    assert str(tmp_path) not in md


def test_markdown_clean_when_no_findings(tmp_path: Path) -> None:
    project = _project(tmp_path, "SELECT user_id FROM dim_users")
    result = scan_dbt_project(project, rules=DEFAULT_RULES)

    md = render_dbt_scan_markdown(result)

    assert md.startswith(COMMENT_MARKER)
    assert "No proven rewrites in 1 scanned model" in md
    assert "```diff" not in md


def test_markdown_cli_format(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from snowprove.cli import main

    project = _project(tmp_path, "SELECT DISTINCT user_id FROM dim_users")
    result = CliRunner().invoke(main, ["dbt", "scan", str(project), "--format", "markdown"])

    assert result.exit_code == 0, result.output
    assert COMMENT_MARKER in result.output
