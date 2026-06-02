from pathlib import Path

from pydantic import BaseModel


class DbtProjectFiles(BaseModel):
    model_sql_files: tuple[Path, ...]
    schema_yml_files: tuple[Path, ...]


class DbtProjectDiscoveryError(ValueError):
    pass


def discover_dbt_project(project_path: Path) -> DbtProjectFiles:
    if not project_path.exists():
        raise DbtProjectDiscoveryError(f"Project path does not exist: {project_path}")
    if not project_path.is_dir():
        raise DbtProjectDiscoveryError(f"Project path is not a directory: {project_path}")

    models_path = project_path / "models"
    if not models_path.exists() or not models_path.is_dir():
        raise DbtProjectDiscoveryError(f"dbt project has no models directory: {models_path}")

    return DbtProjectFiles(
        model_sql_files=tuple(sorted(models_path.rglob("*.sql"))),
        schema_yml_files=tuple(
            sorted(
                [
                    *models_path.rglob("*.yml"),
                    *models_path.rglob("*.yaml"),
                ]
            )
        ),
    )
