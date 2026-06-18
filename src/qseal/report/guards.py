from __future__ import annotations

import re

from qseal.rewrites.base import RewriteSuggestion


def required_guarding_tests(suggestion: RewriteSuggestion) -> tuple[str, ...]:
    return required_guarding_tests_for_assumptions(suggestion.assumptions)


def required_guarding_tests_for_assumptions(
    assumptions: tuple[str, ...],
) -> tuple[str, ...]:
    tests = []
    for assumption in assumptions:
        tests.extend(_tests_for_assumption(assumption))
    return tuple(dict.fromkeys(tests))


def _tests_for_assumption(assumption: str) -> tuple[str, ...]:
    unique_contained = re.match(
        r"^(?P<table>.+) has a trusted non-null unique key contained in \((?P<columns>.+)\)\.$",
        assumption,
    )
    if unique_contained is not None:
        table = unique_contained.group("table")
        columns = _columns(unique_contained.group("columns"))
        return (
            _unique_test(table, columns),
            *(f"dbt test: not_null on {table}.{column}" for column in columns),
        )

    trusted_unique = re.match(
        r"^(?P<table>.+)\.(?P<column>.+) is a trusted unique key\.$",
        assumption,
    )
    if trusted_unique is not None:
        table = trusted_unique.group("table")
        column = trusted_unique.group("column")
        if column.startswith("(") and column.endswith(")"):
            return (_unique_test(table, _columns(column.removeprefix("(").removesuffix(")"))),)
        return (f"dbt test: unique on {table}.{column}",)

    trusted_relationship = re.match(
        r"^(?P<table>.+)\.(?P<column>.+) has a trusted relationship to "
        r"(?P<ref_table>.+)\.(?P<ref_column>.+)\.$",
        assumption,
    )
    if trusted_relationship is not None:
        table = trusted_relationship.group("table")
        columns = _columns(trusted_relationship.group("column"))
        ref_table = trusted_relationship.group("ref_table")
        ref_columns = _columns(trusted_relationship.group("ref_column"))
        if len(columns) > 1 or len(ref_columns) > 1:
            return (
                "dbt test: relationships from "
                f"{table}({', '.join(columns)}) "
                "to "
                f"{ref_table}({', '.join(ref_columns)})",
            )
        return (
            "dbt test: relationships from "
            f"{trusted_relationship.group('table')}.{trusted_relationship.group('column')} "
            "to "
            f"{trusted_relationship.group('ref_table')}.{trusted_relationship.group('ref_column')}",
        )

    accepted_values = re.match(
        r"^(?P<table>.+)\.(?P<column>.+) has accepted values \((?P<values>.+)\)\.$",
        assumption,
    )
    if accepted_values is not None:
        return (
            "dbt test: accepted_values on "
            f"{accepted_values.group('table')}.{accepted_values.group('column')} "
            f"in ({accepted_values.group('values')})",
        )

    trusted_not_null = re.match(
        r"^(?P<table>.+)\.\((?P<column>.+)\) is trusted non-null\.$",
        assumption,
    )
    if trusted_not_null is not None:
        table = trusted_not_null.group("table")
        columns = _columns(trusted_not_null.group("column"))
        return tuple(
            f"dbt test: not_null on {table}.{column}"
            for column in columns
        )

    return ()


def _columns(raw_columns: str) -> tuple[str, ...]:
    raw_columns = raw_columns.strip()
    if raw_columns.startswith("(") and raw_columns.endswith(")"):
        raw_columns = raw_columns.removeprefix("(").removesuffix(")")
    return tuple(column.strip() for column in raw_columns.split(",") if column.strip())


def _unique_test(table: str, columns: tuple[str, ...]) -> str:
    if len(columns) == 1:
        return f"dbt test: unique on {table}.{columns[0]}"
    return f"dbt test: unique combination on {table}({', '.join(columns)})"
