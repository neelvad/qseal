from pathlib import Path

import yaml
from pydantic import BaseModel


class DbtProjectFiles(BaseModel):
    model_sql_files: tuple[Path, ...]
    schema_yml_files: tuple[Path, ...]


class DbtProjectDiscoveryError(ValueError):
    pass


def discover_compiled_sql_path(project_path: Path) -> Path:
    compiled_root = project_path / "target" / "compiled"
    if not compiled_root.exists() or not compiled_root.is_dir():
        raise DbtProjectDiscoveryError(f"dbt compiled directory not found: {compiled_root}")

    project_name = _dbt_project_name(project_path)
    if project_name is not None:
        project_models = compiled_root / project_name / "models"
        if project_models.exists() and tuple(project_models.rglob("*.sql")):
            return project_models

    candidates = _compiled_sql_candidates(compiled_root)
    if not candidates:
        raise DbtProjectDiscoveryError(f"No compiled SQL files found under: {compiled_root}")
    if len(candidates) > 1:
        formatted = ", ".join(str(candidate) for candidate in candidates)
        raise DbtProjectDiscoveryError(
            "Multiple compiled SQL directories found. "
            f"Use --compiled-dir to choose one: {formatted}"
        )
    return candidates[0]


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
        model_sql_files=_discover_model_sql_files(sql_root, models_path, compiled_path),
        schema_yml_files=tuple(
            sorted(
                [
                    *models_path.rglob("*.yml"),
                    *models_path.rglob("*.yaml"),
                ]
            )
        ),
    )


def _discover_model_sql_files(
    sql_root: Path,
    models_path: Path,
    compiled_path: Path | None,
) -> tuple[Path, ...]:
    sql_files = tuple(sorted(sql_root.rglob("*.sql")))
    if compiled_path is None:
        return sql_files

    return tuple(
        sql_file
        for sql_file in sql_files
        if _compiled_source_model_path(sql_file, compiled_path, models_path) is not None
    )


def _compiled_source_model_path(
    sql_file: Path,
    compiled_path: Path,
    models_path: Path,
) -> Path | None:
    relative = _compiled_model_relative_path(compiled_path, sql_file)
    if relative is None:
        return None

    source_path = models_path / relative
    if source_path.exists() and source_path.is_file():
        return source_path
    return None


def _compiled_model_relative_path(compiled_path: Path, sql_file: Path) -> Path | None:
    try:
        relative = sql_file.relative_to(compiled_path)
    except ValueError:
        return None

    if relative.parts and relative.parts[0] == "models":
        return Path(*relative.parts[1:])

    if "models" in relative.parts:
        models_index = relative.parts.index("models")
        return Path(*relative.parts[models_index + 1 :])

    return relative


def _dbt_project_name(project_path: Path) -> str | None:
    project_yml = project_path / "dbt_project.yml"
    if not project_yml.exists():
        return None

    payload = yaml.safe_load(project_yml.read_text()) or {}
    name = payload.get("name")
    return name if isinstance(name, str) and name else None


def _compiled_sql_candidates(compiled_root: Path) -> list[Path]:
    sql_files = sorted(compiled_root.rglob("*.sql"))
    if not sql_files:
        return []

    model_dirs = sorted(
        {
            parent
            for sql_file in sql_files
            for parent in sql_file.parents
            if parent != compiled_root and parent.name == "models"
        }
    )
    if model_dirs:
        return model_dirs

    project_dirs = sorted(
        {
            sql_file.relative_to(compiled_root).parts[0]
            for sql_file in sql_files
            if sql_file.relative_to(compiled_root).parts
        }
    )
    return [compiled_root / project_dir for project_dir in project_dirs]
