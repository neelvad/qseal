import importlib.util
import subprocess
import sys
from pathlib import Path

ENTRYPOINT = Path(__file__).resolve().parents[1] / "scripts" / "action_entrypoint.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("action_entrypoint", ENTRYPOINT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_find_comment_id_matches_marker() -> None:
    module = _load_module()
    comments = [
        {"id": 1, "body": "unrelated"},
        {"id": 2, "body": f"{module.COMMENT_MARKER}\nold report"},
    ]
    assert module.find_comment_id(comments, module.COMMENT_MARKER) == 2
    assert module.find_comment_id([], module.COMMENT_MARKER) is None


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_entrypoint_scans_changed_models_and_fails_on_findings(tmp_path: Path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "schema.yml").write_text(
        "version: 2\nmodels:\n  - name: dim_users\n"
        "    columns: [{name: user_id, tests: [unique, not_null]}]\n"
    )
    (models / "dim_users.sql").write_text("SELECT user_id FROM dim_users")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "tester")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    base = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    (models / "dim_users.sql").write_text("SELECT DISTINCT user_id FROM dim_users")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "edit")

    completed = subprocess.run(
        [sys.executable, str(ENTRYPOINT)],
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "INPUT_PROJECT": str(tmp_path),
            "INPUT_BASE_REF": base,
            "INPUT_FAIL_ON": "findings",
            "INPUT_COMMENT": "false",
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        },
    )

    assert completed.returncode == 1, completed.stderr
    assert "remove_redundant_distinct" in completed.stdout
    assert "models/dim_users.sql" in completed.stdout


def test_entrypoint_clean_when_no_models_changed(tmp_path: Path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "schema.yml").write_text("version: 2\nmodels: []\n")
    (models / "x.sql").write_text("SELECT 1")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "tester")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    base = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    (tmp_path / "README.md").write_text("docs")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "docs")

    completed = subprocess.run(
        [sys.executable, str(ENTRYPOINT)],
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "INPUT_PROJECT": str(tmp_path),
            "INPUT_BASE_REF": base,
            "INPUT_FAIL_ON": "findings",
            "INPUT_COMMENT": "false",
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        },
    )

    assert completed.returncode == 0
    assert "no changed dbt models" in completed.stdout
