from snowprove.constraints.model import ConstraintCatalog, TableConstraints
from snowprove.parser.sqlglot_parser import parse_select
from snowprove.rewrites.base import VerificationStatus
from snowprove.rewrites.distinct import RemoveRedundantDistinct
from snowprove.rewrites.join_elimination import RemoveUnusedLeftJoin
from snowprove.rewrites.not_null_filter import RemoveRedundantNotNullFilter

UNIQUE_USERS = ConstraintCatalog(
    tables={
        "users": TableConstraints(
            columns={"user_id": {"nullable": False}, "email": {"nullable": False}},
            unique=[("user_id",)],
        )
    }
)


def test_parses_qualify_dedup_pattern() -> None:
    query = parse_select(
        """
        SELECT user_id, status
        FROM users
        QUALIFY ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY updated_at DESC) = 1
        """
    )

    assert len(query.qualify) == 1
    assert "ROW_NUMBER()" in query.qualify[0].expression_sql
    assert query.qualify[0].references_unqualified_columns is True
    assert "QUALIFY" in query.to_sql()


def test_removes_redundant_not_null_filter_under_qualify() -> None:
    # The redundant filter provably removes no rows, so QUALIFY window
    # functions evaluate over identical input either way.
    query = parse_select(
        """
        SELECT user_id, status
        FROM users
        WHERE email IS NOT NULL
        QUALIFY ROW_NUMBER() OVER (PARTITION BY status ORDER BY user_id) = 1
        """
    )

    suggestion = RemoveRedundantNotNullFilter().apply(query, UNIQUE_USERS)

    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert "QUALIFY" in suggestion.rewritten_sql
    assert "IS NOT NULL" not in suggestion.rewritten_sql


def test_removes_redundant_distinct_under_qualify() -> None:
    query = parse_select(
        """
        SELECT DISTINCT user_id
        FROM users
        QUALIFY ROW_NUMBER() OVER (ORDER BY user_id) >= 1
        """
    )

    suggestion = RemoveRedundantDistinct().apply(query, UNIQUE_USERS)

    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert "QUALIFY" in suggestion.rewritten_sql
    assert "DISTINCT" not in suggestion.rewritten_sql


def test_refuses_join_elimination_when_qualify_references_joined_table() -> None:
    query = parse_select(
        """
        SELECT f.user_id
        FROM fact_orders f
        LEFT JOIN dim_users u ON f.user_id = u.user_id
        QUALIFY ROW_NUMBER() OVER (PARTITION BY u.org ORDER BY f.ts) = 1
        """
    )
    constraints = ConstraintCatalog(tables={"dim_users": TableConstraints(unique=[("user_id",)])})

    suggestion = RemoveUnusedLeftJoin().apply(query, constraints)

    assert suggestion.status == VerificationStatus.UNKNOWN


def test_eliminates_join_when_qualify_references_only_left_table() -> None:
    query = parse_select(
        """
        SELECT f.user_id
        FROM fact_orders f
        LEFT JOIN dim_users u ON f.user_id = u.user_id
        QUALIFY ROW_NUMBER() OVER (PARTITION BY f.org ORDER BY f.ts) = 1
        """
    )
    constraints = ConstraintCatalog(tables={"dim_users": TableConstraints(unique=[("user_id",)])})

    suggestion = RemoveUnusedLeftJoin().apply(query, constraints)

    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert "QUALIFY" in suggestion.rewritten_sql
