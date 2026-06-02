from pathlib import Path

import pytest

from snowprove.dbt.project import DbtProjectDiscoveryError, discover_dbt_project


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
