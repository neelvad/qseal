import subprocess
from pathlib import Path


class GitDiffError(ValueError):
    pass


def changed_model_paths(project_path: Path, base_ref: str) -> set[Path]:
    """Model SQL files changed versus ``base_ref``, as resolved absolute paths.

    Runs ``git diff`` from the repository containing the dbt project, scoped to
    the project's ``models/`` directory, excluding deletions (a deleted file
    cannot be scanned). The project may sit in a subdirectory of the repo.
    """
    models_path = (project_path / "models").resolve()
    root = _repo_root(project_path)
    output = _run_git(
        root,
        [
            "diff",
            "--name-only",
            "--diff-filter=d",
            base_ref,
            "--",
            str(models_path),
        ],
    )
    changed = set()
    for line in output.splitlines():
        line = line.strip()
        if line.endswith(".sql"):
            changed.add((root / line).resolve())
    return changed


def _repo_root(project_path: Path) -> Path:
    return Path(_run_git(project_path, ["rev-parse", "--show-toplevel"]).strip())


def _run_git(cwd: Path, args: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(cwd), *args],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as error:
        raise GitDiffError("git is required for --changed-since.") from error
    if completed.returncode != 0:
        raise GitDiffError(
            f"git {' '.join(args)} failed: {completed.stderr.strip() or 'unknown error'}"
        )
    return completed.stdout
