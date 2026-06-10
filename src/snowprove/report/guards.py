from __future__ import annotations

import re

from snowprove.rewrites.base import RewriteSuggestion


def required_guarding_tests(suggestion: RewriteSuggestion) -> tuple[str, ...]:
    tests = []
    for assumption in suggestion.assumptions:
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
        return (
            f"dbt test: unique on "
            f"{trusted_unique.group('table')}.{trusted_unique.group('column')}",
        )

    trusted_not_null = re.match(
        r"^(?P<table>.+)\.\((?P<column>.+)\) is trusted non-null\.$",
        assumption,
    )
    if trusted_not_null is not None:
        return (
            f"dbt test: not_null on "
            f"{trusted_not_null.group('table')}.{trusted_not_null.group('column')}",
        )

    return ()


def _columns(raw_columns: str) -> tuple[str, ...]:
    return tuple(column.strip() for column in raw_columns.split(",") if column.strip())


def _unique_test(table: str, columns: tuple[str, ...]) -> str:
    if len(columns) == 1:
        return f"dbt test: unique on {table}.{columns[0]}"
    return f"dbt test: unique combination on {table}({', '.join(columns)})"
