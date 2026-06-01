from pathlib import Path
from typing import Any

import yaml

from snowprove.constraints.model import ColumnConstraint, ConstraintCatalog, TableConstraints


def load_constraints(path: Path) -> ConstraintCatalog:
    payload = yaml.safe_load(path.read_text()) or {}
    tables = {
        table_name: _load_table(table_payload or {})
        for table_name, table_payload in (payload.get("tables") or {}).items()
    }
    return ConstraintCatalog(tables=tables)


def _load_table(payload: dict[str, Any]) -> TableConstraints:
    columns = {
        column_name: ColumnConstraint(**(column_payload or {}))
        for column_name, column_payload in (payload.get("columns") or {}).items()
    }
    unique = [tuple(key) for key in payload.get("unique", [])]
    return TableConstraints(columns=columns, unique=unique)
