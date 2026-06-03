from pathlib import Path

import pytest

from snowprove.dbt.project import (
    DbtProjectDiscoveryError,
    discover_compiled_sql_path,
    discover_dbt_project,
)


def test_discovers_dbt_project_files(tmp_path: Path) -> None:
    models = tmp_path / "models"
    marts = models / "marts"
    marts.mkdir(parents=True)
    (marts / "orders.sql").write_text("SELECT order_id FROM orders")
    (marts / "schema.yml").write_text("models: []")
    (models / "sources.yaml").write_text("sources: []")

    project = discover_dbt_project(tmp_path)

    assert project.model_sql_files == (marts / "orders.sql",)
    assert project.schema_yml_files == (
        marts / "schema.yml",
        models / "sources.yaml",
    )


def test_rejects_project_without_models_directory(tmp_path: Path) -> None:
    with pytest.raises(DbtProjectDiscoveryError, match="models directory"):
        discover_dbt_project(tmp_path)


def test_discovers_compiled_sql_files_when_compiled_path_is_provided(tmp_path: Path) -> None:
    models = tmp_path / "models"
    compiled = tmp_path / "target" / "compiled" / "project" / "models"
    models.mkdir()
    compiled.mkdir(parents=True)
    (models / "schema.yml").write_text("models: []")
    (models / "source_model.sql").write_text("SELECT * FROM {{ ref('orders') }}")
    (compiled / "source_model.sql").write_text("SELECT * FROM orders")

    project = discover_dbt_project(tmp_path, compiled_path=compiled)

    assert project.model_sql_files == (compiled / "source_model.sql",)
    assert project.schema_yml_files == (models / "schema.yml",)


def test_discovers_unambiguous_compiled_sql_path(tmp_path: Path) -> None:
    compiled = tmp_path / "target" / "compiled" / "project" / "models"
    compiled.mkdir(parents=True)
    (compiled / "dim_users.sql").write_text("SELECT user_id FROM dim_users")

    assert discover_compiled_sql_path(tmp_path) == compiled


def test_use_compiled_prefers_dbt_project_name_when_packages_exist(tmp_path: Path) -> None:
    project_compiled = tmp_path / "target" / "compiled" / "snowprove" / "models"
    package_compiled = tmp_path / "target" / "compiled" / "dbt_utils" / "models"
    project_compiled.mkdir(parents=True)
    package_compiled.mkdir(parents=True)
    (tmp_path / "dbt_project.yml").write_text("name: snowprove\n")
    (project_compiled / "dim_users.sql").write_text("SELECT user_id FROM dim_users")
    (package_compiled / "helper.sql").write_text("SELECT helper_id FROM helper")

    assert discover_compiled_sql_path(tmp_path) == project_compiled


def test_rejects_missing_compiled_sql_path(tmp_path: Path) -> None:
    with pytest.raises(DbtProjectDiscoveryError, match="compiled directory"):
        discover_compiled_sql_path(tmp_path)


def test_rejects_ambiguous_compiled_sql_paths(tmp_path: Path) -> None:
    first = tmp_path / "target" / "compiled" / "first" / "models"
    second = tmp_path / "target" / "compiled" / "second" / "models"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    (first / "users.sql").write_text("SELECT user_id FROM users")
    (second / "orders.sql").write_text("SELECT order_id FROM orders")

    with pytest.raises(DbtProjectDiscoveryError, match="Multiple compiled SQL"):
        discover_compiled_sql_path(tmp_path)
