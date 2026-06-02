from snowprove.constraints.model import ConstraintCatalog
from snowprove.parser.sqlglot_parser import parse_select
from snowprove.rewrites.base import VerificationStatus
from snowprove.rewrites.predicate_pushdown import PredicatePushdown


def test_pushes_predicate_through_simple_projection_subquery() -> None:
    query = parse_select(
        """
        SELECT user_id, revenue
        FROM (
          SELECT user_id, revenue
          FROM orders
        ) x
        WHERE revenue > 0
        """
    )

    suggestion = PredicatePushdown().apply(query, ConstraintCatalog())

    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rewritten_sql == "SELECT user_id, revenue\nFROM orders\nWHERE revenue > 0;"


def test_pushes_predicate_while_preserving_inner_predicates() -> None:
    query = parse_select(
        """
        SELECT user_id, revenue
        FROM (
          SELECT user_id, revenue
          FROM orders
          WHERE status = 'active'
        ) x
        WHERE revenue > 0
        """
    )

    suggestion = PredicatePushdown().apply(query, ConstraintCatalog())

    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert (
        suggestion.rewritten_sql
        == "SELECT user_id, revenue\nFROM orders\nWHERE status = 'active' AND revenue > 0;"
    )


def test_pushes_null_predicate_through_simple_projection_subquery() -> None:
    query = parse_select(
        """
        SELECT user_id, email
        FROM (
          SELECT user_id, email
          FROM users
        ) x
        WHERE email IS NOT NULL
        """
    )

    suggestion = PredicatePushdown().apply(query, ConstraintCatalog())

    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rewritten_sql == "SELECT user_id, email\nFROM users\nWHERE email IS NOT NULL;"


def test_refuses_pushdown_when_predicate_references_unprojected_column() -> None:
    query = parse_select(
        """
        SELECT user_id
        FROM (
          SELECT user_id
          FROM orders
        ) x
        WHERE revenue > 0
        """
    )

    suggestion = PredicatePushdown().apply(query, ConstraintCatalog())

    assert suggestion.status == VerificationStatus.UNKNOWN
