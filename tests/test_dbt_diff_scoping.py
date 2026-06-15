import subprocess
from pathlib import Path

import pytest

from snowprove.dbt.git_diff import GitDiffError, changed_model_paths
from snowprove.dbt.scan import scan_dbt_project
from snowprove.rewrites.registry import DEFAULT_RULES


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _init_project(tmp_path: Path) -> tuple[Path, str]:
    """A git repo with two tested models; returns (project_path, base_ref)."""
    models = tmp_path / "models"
    models.mkdir()
    (models / "schema.yml").write_text(
        """
version: 2
models:
  - name: dim_users
    columns: [{name: user_id, tests: [unique, not_null]}]
  - name: dim_accounts
    columns: [{name: account_id, tests: [unique, not_null]}]
"""
    )
    (models / "dim_users.sql").write_text("SELECT user_id FROM dim_users")
    (models / "dim_accounts.sql").write_text("SELECT account_id FROM dim_accounts")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "tester")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    base = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    return tmp_path, base


def test_changed_model_paths_lists_only_edited_models(tmp_path: Path) -> None:
    project, base = _init_project(tmp_path)
    (project / "models" / "dim_users.sql").write_text("SELECT DISTINCT user_id FROM dim_users")
    _git(project, "add", "-A")
    _git(project, "commit", "-qm", "edit")

    changed = changed_model_paths(project, base)

    assert {p.name for p in changed} == {"dim_users.sql"}


def test_changed_model_paths_ignores_non_model_changes(tmp_path: Path) -> None:
    project, base = _init_project(tmp_path)
    (project / "README.md").write_text("docs")
    _git(project, "add", "-A")
    _git(project, "commit", "-qm", "docs")

    assert changed_model_paths(project, base) == set()


def test_scan_only_paths_restricts_to_changed_model(tmp_path: Path) -> None:
    project, base = _init_project(tmp_path)
    (project / "models" / "dim_users.sql").write_text("SELECT DISTINCT user_id FROM dim_users")
    _git(project, "add", "-A")
    _git(project, "commit", "-qm", "edit")
    changed = changed_model_paths(project, base)

    scoped = scan_dbt_project(project, rules=DEFAULT_RULES, only_paths=changed)

    assert scoped.model_count == 1
    assert scoped.proven_finding_count() == 1


def test_scan_only_paths_empty_scans_nothing(tmp_path: Path) -> None:
    project, _ = _init_project(tmp_path)
    result = scan_dbt_project(project, rules=DEFAULT_RULES, only_paths=set())
    assert result.model_count == 0
    assert result.proven_finding_count() == 0


def test_changed_model_paths_errors_outside_git(tmp_path: Path) -> None:
    (tmp_path / "models").mkdir()
    with pytest.raises(GitDiffError):
        changed_model_paths(tmp_path, "HEAD")


def test_dbt_scan_cli_changed_since(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from snowprove.cli import main

    project, base = _init_project(tmp_path)
    (project / "models" / "dim_users.sql").write_text("SELECT DISTINCT user_id FROM dim_users")
    _git(project, "add", "-A")
    _git(project, "commit", "-qm", "edit")

    result = CliRunner().invoke(
        main, ["dbt", "scan", str(project), "--changed-since", base, "--format", "json"]
    )

    assert result.exit_code == 0, result.output
    assert '"model_count": 1' in result.output
