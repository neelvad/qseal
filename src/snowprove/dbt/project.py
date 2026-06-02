from pathlib import Path

from pydantic import BaseModel


class DbtProjectFiles(BaseModel):
    model_sql_files: tuple[Path, ...]
    schema_yml_files: tuple[Path, ...]


class DbtProjectDiscoveryError(ValueError):
    pass


def discover_dbt_project(
    project_path: Path,
    compiled_path: Path | None = None,
) -> DbtProjectFiles:
    if not project_path.exists():
        raise DbtProjectDiscoveryError(f"Project path does not exist: {project_path}")
    if not project_path.is_dir():
        raise DbtProjectDiscoveryError(f"Project path is not a directory: {project_path}")

    models_path = project_path / "models"
    if not models_path.exists() or not models_path.is_dir():
        raise DbtProjectDiscoveryError(f"dbt project has no models directory: {models_path}")

    sql_root = compiled_path or models_path
    if compiled_path is not None:
        if not compiled_path.exists():
            raise DbtProjectDiscoveryError(f"Compiled SQL path does not exist: {compiled_path}")
        if not compiled_path.is_dir():
            raise DbtProjectDiscoveryError(f"Compiled SQL path is not a directory: {compiled_path}")

    return DbtProjectFiles(
        model_sql_files=tuple(sorted(sql_root.rglob("*.sql"))),
        schema_yml_files=tuple(
            sorted(
                [
                    *models_path.rglob("*.yml"),
                    *models_path.rglob("*.yaml"),
                ]
            )
        ),
    )
