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


def test_refuses_join_elimination_with_exists_predicate() -> None:
    query = parse_select(
        """
        SELECT f.user_id
        FROM fact_orders f
        LEFT JOIN dim_users u ON f.user_id = u.user_id
        WHERE EXISTS (
          SELECT 1
          FROM user_flags uf
          WHERE uf.user_id = u.user_id
        )
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


def test_refuses_join_elimination_when_opaque_projection_references_joined_table() -> None:
    query = parse_select(
        """
        SELECT f.user_id, COALESCE(u.name, 'unknown') AS user_name
        FROM fact_orders f
        LEFT JOIN dim_users u ON f.user_id = u.user_id
        """
    )
    constraints = ConstraintCatalog(tables={"dim_users": TableConstraints(unique=[("user_id",)])})

    suggestion = RemoveUnusedLeftJoin().apply(query, constraints)

    assert suggestion.status == VerificationStatus.UNKNOWN


def test_refuses_join_elimination_when_opaque_projection_has_unqualified_columns() -> None:
    query = parse_select(
        """
        SELECT f.user_id, COALESCE(name, 'unknown') AS user_name
        FROM fact_orders f
        LEFT JOIN dim_users u ON f.user_id = u.user_id
        """
    )
    constraints = ConstraintCatalog(tables={"dim_users": TableConstraints(unique=[("user_id",)])})

    suggestion = RemoveUnusedLeftJoin().apply(query, constraints)

    assert suggestion.status == VerificationStatus.UNKNOWN


def test_eliminates_join_when_opaque_projection_references_only_left_table() -> None:
    query = parse_select(
        """
        SELECT f.user_id, COALESCE(f.region, 'unknown') AS region
        FROM fact_orders f
        LEFT JOIN dim_users u ON f.user_id = u.user_id
        """
    )
    constraints = ConstraintCatalog(tables={"dim_users": TableConstraints(unique=[("user_id",)])})

    suggestion = RemoveUnusedLeftJoin().apply(query, constraints)

    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert "COALESCE(f.region, 'unknown') AS region" in suggestion.rewritten_sql


def test_refuses_join_elimination_for_cte_sourced_query() -> None:
    # A standalone rewrite of a query reading from a CTE would drop the WITH
    # clause that defines it.
    query = parse_select(
        """
        WITH x AS (SELECT a, k FROM base WHERE p = 1)
        SELECT x.a FROM x LEFT JOIN dim_users u ON x.k = u.user_id
        """
    )
    constraints = ConstraintCatalog(tables={"dim_users": TableConstraints(unique=[("user_id",)])})

    suggestion = RemoveUnusedLeftJoin().apply(query, constraints)

    assert suggestion.status == VerificationStatus.UNKNOWN
    assert "CTE relation" in suggestion.reason
