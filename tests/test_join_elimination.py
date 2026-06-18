from qseal.constraints.model import (
    ColumnConstraint,
    ConstraintCatalog,
    ForeignKeyConstraint,
    TableConstraints,
)
from qseal.parser.sqlglot_parser import parse_select
from qseal.rewrites.base import VerificationStatus
from qseal.rewrites.join_elimination import RemoveForeignKeyInnerJoin, RemoveUnusedLeftJoin


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


def test_removes_unused_left_join_when_right_composite_key_is_unique() -> None:
    query = parse_select(
        """
        SELECT f.order_id, f.revenue
        FROM fact_orders f
        LEFT JOIN dim_users u
          ON f.tenant_id = u.tenant_id AND f.user_id = u.user_id
        """
    )
    constraints = ConstraintCatalog(
        tables={"dim_users": TableConstraints(unique=[("tenant_id", "user_id")])}
    )

    suggestion = RemoveUnusedLeftJoin().apply(query, constraints)

    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rewritten_sql == "SELECT f.order_id, f.revenue\nFROM fact_orders f;"
    assert suggestion.assumptions == (
        "dim_users.(tenant_id, user_id) is a trusted unique key.",
    )


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


def test_removes_inner_join_when_child_has_non_null_fk_to_unique_parent() -> None:
    query = parse_select(
        """
        SELECT f.order_id, f.user_id, f.revenue
        FROM fact_orders f
        INNER JOIN dim_users u ON f.user_id = u.user_id
        """
    )
    constraints = _fk_constraints()

    suggestion = RemoveForeignKeyInnerJoin().apply(query, constraints)

    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rewritten_sql == (
        "SELECT f.order_id, f.user_id, f.revenue\nFROM fact_orders f;"
    )
    assert suggestion.assumptions == (
        "fact_orders.user_id has a trusted relationship to dim_users.user_id.",
        "fact_orders.(user_id) is trusted non-null.",
        "dim_users.user_id is a trusted unique key.",
    )


def test_removes_inner_join_when_child_has_composite_fk_to_unique_parent() -> None:
    query = parse_select(
        """
        SELECT f.order_id, f.tenant_id, f.user_id
        FROM fact_orders f
        INNER JOIN dim_users u
          ON f.tenant_id = u.tenant_id AND f.user_id = u.user_id
        """
    )
    constraints = ConstraintCatalog(
        tables={
            "fact_orders": TableConstraints(
                columns={
                    "tenant_id": ColumnConstraint(nullable=False),
                    "user_id": ColumnConstraint(nullable=False),
                },
                foreign_keys=[
                    ForeignKeyConstraint(
                        columns=("tenant_id", "user_id"),
                        ref_table="dim_users",
                        ref_columns=("tenant_id", "user_id"),
                    )
                ],
            ),
            "dim_users": TableConstraints(unique=[("tenant_id", "user_id")]),
        }
    )

    suggestion = RemoveForeignKeyInnerJoin().apply(query, constraints)

    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rewritten_sql == (
        "SELECT f.order_id, f.tenant_id, f.user_id\nFROM fact_orders f;"
    )
    assert suggestion.assumptions == (
        "fact_orders.(tenant_id, user_id) has a trusted relationship to "
        "dim_users.(tenant_id, user_id).",
        "fact_orders.(tenant_id, user_id) is trusted non-null.",
        "dim_users.(tenant_id, user_id) is a trusted unique key.",
    )


def test_refuses_inner_join_elimination_when_parent_columns_are_projected() -> None:
    query = parse_select(
        """
        SELECT f.order_id, u.segment
        FROM fact_orders f
        INNER JOIN dim_users u ON f.user_id = u.user_id
        """
    )

    suggestion = RemoveForeignKeyInnerJoin().apply(query, _fk_constraints())

    assert suggestion.status == VerificationStatus.UNKNOWN
    assert "parent relation is referenced" in str(suggestion.reason)


def test_refuses_inner_join_elimination_without_child_not_null() -> None:
    query = parse_select(
        """
        SELECT f.order_id, f.user_id
        FROM fact_orders f
        INNER JOIN dim_users u ON f.user_id = u.user_id
        """
    )
    constraints = ConstraintCatalog(
        tables={
            "fact_orders": TableConstraints(
                foreign_keys=[
                    ForeignKeyConstraint(
                        columns=("user_id",),
                        ref_table="dim_users",
                        ref_columns=("user_id",),
                    )
                ],
            ),
            "dim_users": TableConstraints(unique=[("user_id",)]),
        }
    )

    suggestion = RemoveForeignKeyInnerJoin().apply(query, constraints)

    assert suggestion.status == VerificationStatus.UNKNOWN
    assert "not trusted non-null" in str(suggestion.reason)


def test_refuses_inner_join_elimination_without_relationship_test() -> None:
    query = parse_select(
        """
        SELECT f.order_id, f.user_id
        FROM fact_orders f
        INNER JOIN dim_users u ON f.user_id = u.user_id
        """
    )
    constraints = ConstraintCatalog(
        tables={
            "fact_orders": TableConstraints(
                columns={"user_id": ColumnConstraint(nullable=False)}
            ),
            "dim_users": TableConstraints(unique=[("user_id",)]),
        }
    )

    suggestion = RemoveForeignKeyInnerJoin().apply(query, constraints)

    assert suggestion.status == VerificationStatus.NOT_APPLICABLE
    assert "not known to reference" in str(suggestion.reason)


def _fk_constraints() -> ConstraintCatalog:
    return ConstraintCatalog(
        tables={
            "fact_orders": TableConstraints(
                columns={"user_id": ColumnConstraint(nullable=False)},
                foreign_keys=[
                    ForeignKeyConstraint(
                        columns=("user_id",),
                        ref_table="dim_users",
                        ref_columns=("user_id",),
                    )
                ],
            ),
            "dim_users": TableConstraints(unique=[("user_id",)]),
        }
    )
