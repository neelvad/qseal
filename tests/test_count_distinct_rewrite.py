from qseal.constraints.model import ConstraintCatalog, TableConstraints
from qseal.parser.sqlglot_parser import parse_select
from qseal.rewrites.base import VerificationStatus
from qseal.rewrites.count_distinct import RemoveRedundantCountDistinct


def test_rewrites_count_distinct_on_non_null_unique_key() -> None:
    query = parse_select("SELECT COUNT(DISTINCT user_id) AS unique_users FROM users")
    constraints = _constraints()

    suggestion = RemoveRedundantCountDistinct().apply(query, constraints)

    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rewritten_sql == "SELECT COUNT(user_id) AS unique_users\nFROM users;"
    assert suggestion.assumptions == (
        "users has a trusted non-null unique key contained in (user_id).",
    )


def test_rewrites_unaliased_count_distinct() -> None:
    query = parse_select("SELECT COUNT(DISTINCT user_id) FROM users")
    constraints = _constraints()

    suggestion = RemoveRedundantCountDistinct().apply(query, constraints)

    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rewritten_sql == "SELECT COUNT(user_id)\nFROM users;"


def test_rewrites_count_distinct_with_group_by() -> None:
    query = parse_select(
        """
        SELECT status, COUNT(DISTINCT user_id) AS unique_users
        FROM users
        GROUP BY status
        """
    )
    constraints = _constraints()

    suggestion = RemoveRedundantCountDistinct().apply(query, constraints)

    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rewritten_sql == (
        "SELECT status, COUNT(user_id) AS unique_users\n"
        "FROM users\n"
        "GROUP BY status;"
    )


def test_rejects_count_distinct_without_non_null_unique_key() -> None:
    query = parse_select("SELECT COUNT(DISTINCT user_id) AS unique_users FROM users")
    constraints = ConstraintCatalog(
        tables={"users": TableConstraints(unique=[("user_id",)])}
    )

    suggestion = RemoveRedundantCountDistinct().apply(query, constraints)

    assert suggestion.status == VerificationStatus.UNKNOWN
    assert suggestion.rewritten_sql is None


def test_rejects_count_distinct_with_join() -> None:
    query = parse_select(
        """
        SELECT COUNT(DISTINCT u.user_id) AS unique_users
        FROM users u
        INNER JOIN orders o ON u.user_id = o.user_id
        """
    )

    suggestion = RemoveRedundantCountDistinct().apply(query, _constraints())

    assert suggestion.status == VerificationStatus.NOT_APPLICABLE
    assert suggestion.rewritten_sql is None


def _constraints() -> ConstraintCatalog:
    return ConstraintCatalog(
        tables={
            "users": TableConstraints(
                columns={"user_id": {"nullable": False}},
                unique=[("user_id",)],
            )
        }
    )
