import re
from pathlib import Path
from typing import Any

import yaml

from qseal.constraints.model import (
    ColumnConstraint,
    ConstraintCatalog,
    ForeignKeyConstraint,
    TableConstraints,
)


def load_dbt_constraints(path: Path) -> ConstraintCatalog:
    payload = yaml.safe_load(path.read_text()) or {}
    tables = {}

    for model in payload.get("models", []) or []:
        table_name = model.get("name")
        if not table_name:
            continue
        _add_table_constraints(tables, table_name, _constraints_for_relation(model))

    for source in payload.get("sources", []) or []:
        for source_table in source.get("tables", []) or []:
            table_name = source_table.get("name")
            if not table_name:
                continue
            _add_table_constraints(
                tables,
                table_name,
                _constraints_for_relation(source_table),
            )

    return ConstraintCatalog(tables=tables)


def _constraints_for_relation(relation: dict[str, Any]) -> TableConstraints:
    columns = {}
    unique = []
    foreign_keys = []
    for column in relation.get("columns", []) or []:
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
        foreign_keys.extend(
            _relationships_for_column(
                column_name,
                column.get("tests", []) or [],
            )
        )

    return TableConstraints(
        columns=columns,
        unique=unique,
        foreign_keys=foreign_keys,
    )


def _add_table_constraints(
    tables: dict[str, TableConstraints],
    table_name: str,
    constraints: TableConstraints,
) -> None:
    existing = tables.get(table_name)
    if existing is None:
        tables[table_name] = constraints
        return
    tables[table_name] = TableConstraints(
        columns=_merge_columns(existing.columns, constraints.columns),
        unique=[*existing.unique, *constraints.unique],
        foreign_keys=[*existing.foreign_keys, *constraints.foreign_keys],
    )


def _merge_columns(
    left: dict[str, ColumnConstraint],
    right: dict[str, ColumnConstraint],
) -> dict[str, ColumnConstraint]:
    columns = {}
    for column_name in left.keys() | right.keys():
        left_constraint = left.get(column_name)
        right_constraint = right.get(column_name)
        if (
            (left_constraint is not None and left_constraint.nullable is False)
            or (right_constraint is not None and right_constraint.nullable is False)
        ):
            columns[column_name] = ColumnConstraint(nullable=False)
            continue
        columns[column_name] = right_constraint or left_constraint or ColumnConstraint()
    return columns


def _test_name(test: Any) -> str:
    if isinstance(test, str):
        return test
    if isinstance(test, dict) and test:
        return next(iter(test))
    return ""


def _relationships_for_column(
    column_name: str,
    tests: list[Any],
) -> list[ForeignKeyConstraint]:
    relationships = []
    for test in tests:
        if not isinstance(test, dict):
            continue
        payload = test.get("relationships")
        if not isinstance(payload, dict):
            continue
        arguments = payload.get("arguments")
        if isinstance(arguments, dict):
            payload = {**payload, **arguments}

        ref_table = _relationship_table(payload.get("to"))
        ref_column = payload.get("field")
        if not ref_table or not isinstance(ref_column, str) or not ref_column:
            continue
        relationships.append(
            ForeignKeyConstraint(
                columns=(column_name,),
                ref_table=ref_table,
                ref_columns=(ref_column,),
            )
        )
    return relationships


def _relationship_table(raw_value: Any) -> str | None:
    if not isinstance(raw_value, str):
        return None
    value = raw_value.strip()
    ref_match = re.fullmatch(
        r"\{?\{?\s*ref\(['\"](?P<table>[^'\"]+)['\"]\)\s*\}?\}?",
        value,
    )
    if ref_match is not None:
        return ref_match.group("table")
    source_match = re.fullmatch(
        r"\{?\{?\s*source\(['\"][^'\"]+['\"],\s*['\"](?P<table>[^'\"]+)['\"]\)\s*\}?\}?",
        value,
    )
    if source_match is not None:
        return source_match.group("table")
    return value.strip("'\"").split(".")[-1]
