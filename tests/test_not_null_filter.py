from qseal.constraints.model import ColumnConstraint, ConstraintCatalog, TableConstraints
from qseal.parser.sqlglot_parser import parse_select
from qseal.rewrites.base import VerificationStatus
from qseal.rewrites.not_null_filter import RemoveRedundantNotNullFilter


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


def test_removes_table_qualified_not_null_filter_without_alias() -> None:
    # ``users.email IS NOT NULL`` on an unaliased ``FROM users`` should be
    # recognized: the prefix matches the table name, not just an alias.
    query = parse_select("SELECT user_id FROM users WHERE users.email IS NOT NULL")
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


def test_matches_tolerates_in_and_exists_predicates() -> None:
    from qseal.constraints.model import ConstraintCatalog, TableConstraints
    from qseal.parser.sqlglot_parser import parse_select
    from qseal.rewrites.not_null_filter import RemoveRedundantNotNullFilter

    query = parse_select(
        """
        SELECT user_id FROM users
        WHERE email IS NOT NULL
          AND status IN ('active', 'trial')
          AND EXISTS (SELECT 1 FROM orders o WHERE o.user_id = users.user_id)
        """
    )
    constraints = ConstraintCatalog(
        tables={"users": TableConstraints(columns={"email": {"nullable": False}})}
    )

    matches = RemoveRedundantNotNullFilter().matches(query, constraints)
    assert len(matches) == 1
