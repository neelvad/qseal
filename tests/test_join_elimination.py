from snowprove.constraints.model import ConstraintCatalog, TableConstraints
from snowprove.parser.sqlglot_parser import parse_select
from snowprove.rewrites.base import VerificationStatus
from snowprove.rewrites.join_elimination import RemoveUnusedLeftJoin


def test_removes_unused_left_join_when_right_key_is_unique() -> None:
    query = parse_select(
        """
        SELECT f.user_id, f.revenue
        FROM fact_orders f
        LEFT JOIN dim_users u ON f.user_id = u.user_id
        """
    )
    constraints = ConstraintCatalog(tables={"dim_users": TableConstraints(unique=[("user_id",)])})

    suggestion = RemoveUnusedLeftJoin().apply(query, constraints)

    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rewritten_sql == "SELECT f.user_id, f.revenue\nFROM fact_orders f;"


def test_removes_unused_left_join_from_qualified_relations() -> None:
    query = parse_select(
        """
        SELECT f.user_id, f.revenue
        FROM analytics.public.fact_orders f
        LEFT JOIN analytics.public.dim_users u ON f.user_id = u.user_id
        """
    )
    constraints = ConstraintCatalog(tables={"dim_users": TableConstraints(unique=[("user_id",)])})

    suggestion = RemoveUnusedLeftJoin().apply(query, constraints)

    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rewritten_sql == (
        "SELECT f.user_id, f.revenue\nFROM analytics.public.fact_orders f;"
    )


def test_refuses_join_elimination_when_joined_table_is_projected() -> None:
    query = parse_select(
        """
        SELECT f.user_id, u.email
        FROM fact_orders f
        LEFT JOIN dim_users u ON f.user_id = u.user_id
        """
    )
    constraints = ConstraintCatalog(tables={"dim_users": TableConstraints(unique=[("user_id",)])})

    suggestion = RemoveUnusedLeftJoin().apply(query, constraints)

    assert suggestion.status == VerificationStatus.UNKNOWN


def test_refuses_join_elimination_without_unique_right_key() -> None:
    query = parse_select(
        """
        SELECT f.user_id, f.revenue
        FROM fact_orders f
        LEFT JOIN dim_users u ON f.user_id = u.user_id
        """
    )

    suggestion = RemoveUnusedLeftJoin().apply(query, ConstraintCatalog())

    assert suggestion.status == VerificationStatus.UNKNOWN
