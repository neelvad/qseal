from snowprove.constraints.model import ColumnConstraint, ConstraintCatalog, TableConstraints
from snowprove.parser.sqlglot_parser import parse_select
from snowprove.rewrites.base import VerificationStatus
from snowprove.rewrites.not_null_filter import RemoveRedundantNotNullFilter


def test_removes_redundant_not_null_filter() -> None:
    query = parse_select("SELECT user_id FROM users WHERE email IS NOT NULL")
    constraints = ConstraintCatalog(
        tables={
            "users": TableConstraints(
                columns={"email": ColumnConstraint(nullable=False)},
            )
        }
    )

    suggestion = RemoveRedundantNotNullFilter().apply(query, constraints)

    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rewritten_sql == "SELECT user_id\nFROM users;"


def test_removes_redundant_not_null_filter_from_qualified_relation() -> None:
    query = parse_select(
        "SELECT user_id FROM analytics.public.users WHERE email IS NOT NULL"
    )
    constraints = ConstraintCatalog(
        tables={
            "users": TableConstraints(
                columns={"email": ColumnConstraint(nullable=False)},
            )
        }
    )

    suggestion = RemoveRedundantNotNullFilter().apply(query, constraints)

    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rewritten_sql == "SELECT user_id\nFROM analytics.public.users;"


def test_preserves_non_redundant_predicates() -> None:
    query = parse_select("SELECT user_id FROM users WHERE email IS NOT NULL AND status = 'active'")
    constraints = ConstraintCatalog(
        tables={
            "users": TableConstraints(
                columns={"email": ColumnConstraint(nullable=False)},
            )
        }
    )

    suggestion = RemoveRedundantNotNullFilter().apply(query, constraints)

    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rewritten_sql == "SELECT user_id\nFROM users\nWHERE status = 'active';"


def test_removes_redundant_not_null_filter_before_grouping() -> None:
    query = parse_select(
        """
        SELECT order_id AS unique_field, COUNT(*) AS n_records
        FROM orders
        WHERE order_id IS NOT NULL
        GROUP BY order_id
        HAVING COUNT(*) > 1
        """
    )
    constraints = ConstraintCatalog(
        tables={
            "orders": TableConstraints(
                columns={"order_id": ColumnConstraint(nullable=False)},
            )
        }
    )

    suggestion = RemoveRedundantNotNullFilter().apply(query, constraints)

    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rewritten_sql == (
        "SELECT order_id AS unique_field, COUNT(*) AS n_records\n"
        "FROM orders\n"
        "GROUP BY order_id\n"
        "HAVING COUNT(*) > 1;"
    )


def test_does_not_remove_nullable_not_null_filter() -> None:
    query = parse_select("SELECT user_id FROM users WHERE email IS NOT NULL")
    constraints = ConstraintCatalog(
        tables={
            "users": TableConstraints(
                columns={"email": ColumnConstraint(nullable=True)},
            )
        }
    )

    suggestion = RemoveRedundantNotNullFilter().apply(query, constraints)

    assert suggestion.status == VerificationStatus.NOT_APPLICABLE
