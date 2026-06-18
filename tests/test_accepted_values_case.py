from qseal.constraints.model import (
    AcceptedValue,
    ColumnConstraint,
    ConstraintCatalog,
    TableConstraints,
)
from qseal.parser.sqlglot_parser import parse_select
from qseal.rewrites.accepted_values_case import SimplifyAcceptedValuesCase
from qseal.rewrites.base import VerificationStatus


def test_removes_impossible_case_branch() -> None:
    query = parse_select(
        """
        SELECT
          CASE
            WHEN status = 'cancelled' THEN 'bad'
            ELSE 'ok'
          END AS status_group
        FROM orders
        """
    )

    suggestion = SimplifyAcceptedValuesCase().apply(query, _status_constraints())

    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rewritten_sql == "SELECT 'ok' AS status_group\nFROM orders;"


def test_replaces_case_when_first_reachable_branch_is_always_true() -> None:
    query = parse_select(
        """
        SELECT
          CASE
            WHEN status = 'cancelled' THEN 'bad'
            WHEN status IN ('placed', 'shipped') THEN 'ok'
            ELSE 'other'
          END AS status_group
        FROM orders
        """
    )

    suggestion = SimplifyAcceptedValuesCase().apply(query, _status_constraints())

    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rewritten_sql == "SELECT 'ok' AS status_group\nFROM orders;"
    assert suggestion.assumptions == (
        "orders.status has accepted values ('placed', 'shipped').",
        "orders.(status) is trusted non-null.",
    )


def test_keeps_case_when_domain_partially_overlaps_predicate() -> None:
    query = parse_select(
        """
        SELECT CASE WHEN status IN ('placed', 'cancelled') THEN 'mixed' ELSE 'other' END AS label
        FROM orders
        """
    )

    suggestion = SimplifyAcceptedValuesCase().apply(query, _status_constraints())

    assert suggestion.status == VerificationStatus.NOT_APPLICABLE
    assert suggestion.rewritten_sql is None


def test_keeps_case_without_not_null_premise() -> None:
    query = parse_select(
        "SELECT CASE WHEN status = 'cancelled' THEN 'bad' ELSE 'ok' END AS label FROM orders"
    )
    constraints = ConstraintCatalog(
        tables={
            "orders": TableConstraints(
                columns={
                    "status": ColumnConstraint(
                        nullable=True,
                        accepted_values=(
                            AcceptedValue(value="placed"),
                            AcceptedValue(value="shipped"),
                        ),
                    )
                }
            )
        }
    )

    suggestion = SimplifyAcceptedValuesCase().apply(query, constraints)

    assert suggestion.status == VerificationStatus.NOT_APPLICABLE
    assert suggestion.rewritten_sql is None


def test_accepted_values_case_exposes_structured_matches() -> None:
    query = parse_select(
        "SELECT CASE WHEN status = 'cancelled' THEN 'bad' ELSE 'ok' END AS label FROM orders"
    )
    rule = SimplifyAcceptedValuesCase()

    matches = rule.matches(query, _status_constraints())

    assert len(matches) == 1
    assert matches[0].match_id == "projection:0"
    suggestion = rule.apply_match(query, _status_constraints(), matches[0])
    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT


def _status_constraints() -> ConstraintCatalog:
    return ConstraintCatalog(
        tables={
            "orders": TableConstraints(
                columns={
                    "status": ColumnConstraint(
                        nullable=False,
                        accepted_values=(
                            AcceptedValue(value="placed"),
                            AcceptedValue(value="shipped"),
                        ),
                    )
                }
            )
        }
    )
