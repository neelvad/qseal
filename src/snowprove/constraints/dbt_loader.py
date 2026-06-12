from pathlib import Path
from typing import Any

import yaml

from snowprove.constraints.model import ColumnConstraint, ConstraintCatalog, TableConstraints


def load_dbt_constraints(path: Path) -> ConstraintCatalog:
    payload = yaml.safe_load(path.read_text()) or {}
    tables = {}

    for model in payload.get("models", []) or []:
        table_name = model.get("name")
        if not table_name:
            continue

        columns = {}
        unique = []
        for column in model.get("columns", []) or []:
            column_name = column.get("name")
            if not column_name:
                continue

            test_names = {_test_name(test) for test in column.get("tests", []) or []}
            # Every declared column is recorded; nullable stays unknown unless
            # a not_null test makes it trusted. Declared column lists let
            # downstream consumers (solver schemas, column attribution) know
            # which table owns a column.
            columns[column_name] = ColumnConstraint(
                nullable=False if "not_null" in test_names else None
            )
            if "unique" in test_names:
                unique.append((column_name,))

        tables[table_name] = TableConstraints(columns=columns, unique=unique)

    return ConstraintCatalog(tables=tables)


def _test_name(test: Any) -> str:
    if isinstance(test, str):
        return test
    if isinstance(test, dict) and test:
        return next(iter(test))
    return ""
