from pathlib import Path
from typing import Any

import yaml

from snowprove.constraints.dbt_loader import load_dbt_constraints
from snowprove.constraints.model import ConstraintCatalog
from snowprove.constraints.yaml_loader import load_constraints


def load_constraint_catalog(path: Path, schema_format: str = "auto") -> ConstraintCatalog:
    if schema_format == "snowprove":
        return load_constraints(path)
    if schema_format == "dbt":
        return load_dbt_constraints(path)
    if schema_format != "auto":
        raise ValueError(f"Unsupported schema format: {schema_format}")

    payload = yaml.safe_load(path.read_text()) or {}
    detected = detect_schema_format(payload)
    if detected == "snowprove":
        return load_constraints(path)
    if detected == "dbt":
        return load_dbt_constraints(path)

    raise ValueError("Could not detect schema format. Expected top-level 'tables' or 'models'.")


def detect_schema_format(payload: dict[str, Any]) -> str | None:
    if "tables" in payload:
        return "snowprove"
    if "models" in payload:
        return "dbt"
    return None
