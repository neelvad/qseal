from pathlib import Path
from typing import Any

import yaml

from qseal.constraints.model import (
    ColumnConstraint,
    ConstraintCatalog,
    ForeignKeyConstraint,
    TableConstraints,
)


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
    foreign_keys = [
        ForeignKeyConstraint(
            columns=tuple(foreign_key.get("columns", ())),
            ref_table=foreign_key.get("ref_table", ""),
            ref_columns=tuple(foreign_key.get("ref_columns", ())),
        )
        for foreign_key in payload.get("foreign_keys", [])
        if isinstance(foreign_key, dict)
    ]
    return TableConstraints(columns=columns, unique=unique, foreign_keys=foreign_keys)
