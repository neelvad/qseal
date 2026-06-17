from qseal.constraints.model import (
    AcceptedValue,
    ColumnConstraint,
    ConstraintCatalog,
    TableConstraints,
)
from qseal.parser.sqlglot_parser import parse_select
from qseal.rewrites.accepted_values_filter import RemoveRedundantAcceptedValuesFilter
from qseal.rewrites.base import VerificationStatus


def test_removes_redundant_accepted_values_filter() -> None:
    query = parse_select(
        "SELECT order_id FROM orders WHERE status IN ('placed', 'shipped')"
    )
    constraints = _status_constraints(nullable=False)

    suggestion = RemoveRedundantAcceptedValuesFilter().apply(query, constraints)

    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rewritten_sql == "SELECT order_id\nFROM orders;"
    assert suggestion.assumptions == (
        "orders.status has accepted values ('placed', 'shipped').",
        "orders.(status) is trusted non-null.",
    )


def test_preserves_other_predicates() -> None:
    query = parse_select(
        """
        SELECT order_id FROM orders
        WHERE status IN ('placed', 'shipped') AND priority = 1
        """
    )

    suggestion = RemoveRedundantAcceptedValuesFilter().apply(
        query,
        _status_constraints(nullable=False),
    )

    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rewritten_sql == "SELECT order_id\nFROM orders\nWHERE priority = 1;"


def test_rejects_partial_accepted_values_filter() -> None:
    query = parse_select("SELECT order_id FROM orders WHERE status IN ('placed')")

    suggestion = RemoveRedundantAcceptedValuesFilter().apply(
        query,
        _status_constraints(nullable=False),
    )

    assert suggestion.status == VerificationStatus.NOT_APPLICABLE
    assert suggestion.rewritten_sql is None


def test_rejects_nullable_accepted_values_filter() -> None:
    query = parse_select(
        "SELECT order_id FROM orders WHERE status IN ('placed', 'shipped')"
    )

    suggestion = RemoveRedundantAcceptedValuesFilter().apply(
        query,
        _status_constraints(nullable=True),
    )

    assert suggestion.status == VerificationStatus.NOT_APPLICABLE
    assert suggestion.rewritten_sql is None


def test_removes_unquoted_numeric_accepted_values_filter() -> None:
    query = parse_select("SELECT order_id FROM orders WHERE priority IN (1, 2)")
    constraints = ConstraintCatalog(
        tables={
            "orders": TableConstraints(
                columns={
                    "priority": ColumnConstraint(
                        nullable=False,
                        accepted_values=(
                            AcceptedValue(value="1", is_string=False),
                            AcceptedValue(value="2", is_string=False),
                        ),
                    )
                }
            )
        }
    )

    suggestion = RemoveRedundantAcceptedValuesFilter().apply(query, constraints)

    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rewritten_sql == "SELECT order_id\nFROM orders;"


def test_accepted_values_filter_exposes_structured_matches() -> None:
    query = parse_select(
        "SELECT order_id FROM orders WHERE status IN ('placed', 'shipped')"
    )
    rule = RemoveRedundantAcceptedValuesFilter()

    matches = rule.matches(query, _status_constraints(nullable=False))

    assert len(matches) == 1
    assert matches[0].match_id == "predicate:0"
    suggestion = rule.apply_match(query, _status_constraints(nullable=False), matches[0])
    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT


def _status_constraints(nullable: bool) -> ConstraintCatalog:
    return ConstraintCatalog(
        tables={
            "orders": TableConstraints(
                columns={
                    "status": ColumnConstraint(
                        nullable=nullable,
                        accepted_values=(
                            AcceptedValue(value="placed"),
                            AcceptedValue(value="shipped"),
                        ),
                    )
                }
            )
        }
    )
