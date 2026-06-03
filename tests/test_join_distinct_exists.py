from snowprove.constraints.model import ConstraintCatalog
from snowprove.parser.sqlglot_parser import parse_select
from snowprove.rewrites.base import VerificationStatus
from snowprove.rewrites.join_distinct_exists import RewriteJoinDistinctToExists


def test_rewrites_join_distinct_to_exists() -> None:
    query = parse_select(
        """
        SELECT DISTINCT u.user_id
        FROM users u
        JOIN orders o ON u.user_id = o.user_id
        """
    )

    suggestion = RewriteJoinDistinctToExists().apply(query, ConstraintCatalog())

    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rewritten_sql == (
        "SELECT u.user_id\n"
        "FROM users u\n"
        "WHERE EXISTS (\n"
        "  SELECT 1\n"
        "  FROM orders o\n"
        "  WHERE u.user_id = o.user_id\n"
        ");"
    )


def test_rewrites_qualified_join_distinct_to_exists() -> None:
    query = parse_select(
        """
        SELECT DISTINCT u.user_id
        FROM analytics.public.users u
        JOIN analytics.public.orders o ON u.user_id = o.user_id
        """
    )

    suggestion = RewriteJoinDistinctToExists().apply(query, ConstraintCatalog())

    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert "FROM analytics.public.users u" in str(suggestion.rewritten_sql)
    assert "FROM analytics.public.orders o" in str(suggestion.rewritten_sql)


def test_rewrites_join_distinct_to_exists_with_left_predicate() -> None:
    query = parse_select(
        """
        SELECT DISTINCT u.user_id
        FROM users u
        JOIN orders o ON u.user_id = o.user_id
        WHERE u.status = 'active'
        """
    )

    suggestion = RewriteJoinDistinctToExists().apply(query, ConstraintCatalog())

    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rewritten_sql == (
        "SELECT u.user_id\n"
        "FROM users u\n"
        "WHERE u.status = 'active' AND EXISTS (\n"
        "  SELECT 1\n"
        "  FROM orders o\n"
        "  WHERE u.user_id = o.user_id\n"
        ");"
    )


def test_rejects_join_distinct_to_exists_when_projection_uses_joined_relation() -> None:
    query = parse_select(
        """
        SELECT DISTINCT o.order_id
        FROM users u
        JOIN orders o ON u.user_id = o.user_id
        """
    )

    suggestion = RewriteJoinDistinctToExists().apply(query, ConstraintCatalog())

    assert suggestion.status == VerificationStatus.UNKNOWN


def test_rejects_join_distinct_to_exists_with_joined_where_predicate() -> None:
    query = parse_select(
        """
        SELECT DISTINCT u.user_id
        FROM users u
        JOIN orders o ON u.user_id = o.user_id
        WHERE o.status = 'open'
        """
    )

    suggestion = RewriteJoinDistinctToExists().apply(query, ConstraintCatalog())

    assert suggestion.status == VerificationStatus.UNKNOWN


def test_join_distinct_to_exists_requires_inner_join() -> None:
    query = parse_select(
        """
        SELECT DISTINCT u.user_id
        FROM users u
        LEFT JOIN orders o ON u.user_id = o.user_id
        """
    )

    suggestion = RewriteJoinDistinctToExists().apply(query, ConstraintCatalog())

    assert suggestion.status == VerificationStatus.NOT_APPLICABLE
