import re
from pathlib import Path
from typing import Any

import yaml

from qseal.constraints.model import (
    AcceptedValue,
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

        column_tests = _tests(column)
        test_names = {_test_name(test) for test in column_tests}
        # Every declared column is recorded; nullable stays unknown unless
        # a not_null test makes it trusted. Declared column lists let
        # downstream consumers (solver schemas, column attribution) know
        # which table owns a column.
        columns[column_name] = ColumnConstraint(
            nullable=False if "not_null" in test_names else None,
            accepted_values=_accepted_values_for_column(column_tests),
        )
        if "unique" in test_names:
            unique.append((column_name,))
        foreign_keys.extend(
            _relationships_for_column(
                column_name,
                column_tests,
            )
        )

    unique.extend(_unique_combinations_for_relation(relation))
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
            nullable = False
        else:
            nullable = (right_constraint or left_constraint or ColumnConstraint()).nullable
        accepted_values = ()
        if left_constraint is not None:
            accepted_values = left_constraint.accepted_values
        if right_constraint is not None and right_constraint.accepted_values:
            accepted_values = right_constraint.accepted_values
        columns[column_name] = ColumnConstraint(
            nullable=nullable,
            accepted_values=accepted_values,
        )
    return columns


def _test_name(test: Any) -> str:
    if isinstance(test, str):
        return test
    if isinstance(test, dict) and test:
        return next(iter(test))
    return ""


def _tests(node: dict[str, Any]) -> list[Any]:
    return [*(node.get("tests") or []), *(node.get("data_tests") or [])]


def _unique_combinations_for_relation(relation: dict[str, Any]) -> list[tuple[str, ...]]:
    combinations = []
    for test in _tests(relation):
        test_name = _test_name(test)
        if test_name.split(".")[-1] != "unique_combination_of_columns":
            continue
        payload = test.get(test_name) if isinstance(test, dict) else None
        if not isinstance(payload, dict):
            continue
        arguments = payload.get("arguments")
        if isinstance(arguments, dict):
            payload = {**payload, **arguments}
        raw_columns = payload.get("combination_of_columns")
        if not isinstance(raw_columns, list):
            continue
        columns = tuple(column for column in raw_columns if isinstance(column, str) and column)
        if columns:
            combinations.append(columns)
    return combinations


def _accepted_values_for_column(tests: list[Any]) -> tuple[AcceptedValue, ...]:
    for test in tests:
        test_name = _test_name(test)
        if test_name != "accepted_values":
            continue
        payload = test.get(test_name) if isinstance(test, dict) else None
        if not isinstance(payload, dict):
            continue
        arguments = payload.get("arguments")
        if isinstance(arguments, dict):
            payload = {**payload, **arguments}
        raw_values = payload.get("values")
        if not isinstance(raw_values, list):
            continue
        quote_values = payload.get("quote") is not False
        return tuple(
            AcceptedValue(
                value=str(value),
                is_string=quote_values and isinstance(value, str),
            )
            for value in raw_values
            if isinstance(value, str | int | float)
        )
    return ()


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
