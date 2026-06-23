from qseal.constraints.model import ConstraintCatalog, TableConstraints
from qseal.parser.fragments import parse_select_fragments, replace_fragment_sql
from qseal.parser.sqlglot_parser import parse_select
from qseal.rewrites.base import VerificationStatus
from qseal.rewrites.distinct import RemoveRedundantDistinct
from qseal.rewrites.join_elimination import RemoveUnusedLeftJoin
from qseal.rewrites.subtree import suggest_subtree_rewrites

UNSUPPORTED_OUTER_SQL = """
with active_users as (
    select distinct user_id
    from stg_users
    where status = 'active'
),
user_orders as (
    select
        active_users.user_id,
        count(order_id) as order_count
    from orders
    left join active_users on orders.user_id = active_users.user_id
    group by active_users.user_id
)
select * from user_orders
"""

UNIQUE_STG_USERS = ConstraintCatalog(
    tables={
        "stg_users": TableConstraints(
            columns={"user_id": {"nullable": False}},
            unique=[("user_id",)],
        )
    }
)


def test_parse_select_fragments_enumerates_ctes_and_outer_query() -> None:
    fragments = parse_select_fragments(UNSUPPORTED_OUTER_SQL)

    assert [fragment.location for fragment in fragments] == [
        "cte:active_users",
        "cte:user_orders",
        "query",
    ]
    assert fragments[0].query is not None
    # The DISTINCT CTE is accepted as an opaque named relation; the later
    # fragment that references it parses too, since rewrite rules conservatively
    # abstain on opaque relations.
    assert fragments[1].query is not None
    assert fragments[1].error is None


def test_parse_select_fragments_returns_nothing_without_with_clause() -> None:
    assert parse_select_fragments("SELECT user_id FROM users") == ()


def test_fragment_resolves_only_preceding_ctes() -> None:
    sql = """
    with first as (
        select * from second
    ),
    second as (
        select * from base_table
    )
    select * from second
    """

    fragments = parse_select_fragments(sql)

    # `second` is defined after `first`, so inside `first` it is a base table.
    first = fragments[0]
    assert first.query is not None
    assert first.query.table == "second"
    assert first.query.table_is_cte is False


def test_replace_fragment_sql_rewrites_one_cte_body() -> None:
    replaced = replace_fragment_sql(
        UNSUPPORTED_OUTER_SQL,
        "cte:active_users",
        "SELECT user_id\nFROM stg_users\nWHERE status = 'active';",
    )

    assert "DISTINCT" not in replaced.upper()
    assert "GROUP BY" in replaced.upper()
    assert "WITH active_users AS" in replaced


def test_replace_fragment_sql_rewrites_outer_query_and_keeps_ctes() -> None:
    sql = """
    with base as (
        select * from users
    )
    select distinct user_id from other_table
    """

    replaced = replace_fragment_sql(sql, "query", "SELECT user_id\nFROM other_table;")

    assert "WITH base AS" in replaced
    assert "DISTINCT" not in replaced.upper()


def test_suggest_subtree_rewrites_proves_distinct_removal_inside_cte() -> None:
    suggestions = suggest_subtree_rewrites(UNSUPPORTED_OUTER_SQL, UNIQUE_STG_USERS)

    assert len(suggestions) == 1
    suggestion = suggestions[0]
    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rule_name == "remove_redundant_distinct"
    assert "CTE 'active_users'" in suggestion.reason
    assert suggestion.assumptions
    assert "DISTINCT" not in suggestion.rewritten_sql.upper()
    assert "GROUP BY" in suggestion.rewritten_sql.upper()


def test_suggest_subtree_rewrites_requires_constraints() -> None:
    suggestions = suggest_subtree_rewrites(UNSUPPORTED_OUTER_SQL, ConstraintCatalog())

    assert suggestions == []


def test_suggest_subtree_rewrites_handles_unparseable_sql() -> None:
    assert suggest_subtree_rewrites("{% set x = 1 %} select 1", ConstraintCatalog()) == []


def test_opaque_cte_name_does_not_inherit_base_table_constraints() -> None:
    # The CTE `orders` is not the constrained `orders` model, so its trusted
    # unique key must not justify DISTINCT removal inside the outer query.
    sql = """
    with orders as (
        select order_id from raw_orders where status = 'open'
    )
    select distinct order_id from orders
    """
    constraints = ConstraintCatalog(
        tables={
            "orders": TableConstraints(
                columns={"order_id": {"nullable": False}},
                unique=[("order_id",)],
            )
        }
    )

    query = parse_select(sql)
    assert query.table_is_cte is True
    assert query.table_name() is None

    suggestion = RemoveRedundantDistinct().apply(query, constraints)
    assert suggestion.status != VerificationStatus.PROVEN_EQUIVALENT


def test_opaque_cte_join_target_does_not_inherit_base_table_constraints() -> None:
    cte_sql = """
    with dim_users as (
        select user_id from raw_users where x = 1
    )
    select f.user_id, f.revenue
    from fact_orders f
    left join dim_users on f.user_id = dim_users.user_id
    """
    constraints = ConstraintCatalog(
        tables={"dim_users": TableConstraints(unique=[("user_id",)])}
    )

    query = parse_select(cte_sql)
    assert query.joins[0].table_is_cte is True

    suggestion = RemoveUnusedLeftJoin().apply(query, constraints)
    assert suggestion.status != VerificationStatus.PROVEN_EQUIVALENT


def test_passthrough_cte_join_target_resolves_to_base_table_constraints() -> None:
    sql = """
    with dim_users as (
        select * from stg_users
    )
    select f.user_id, f.revenue
    from fact_orders f
    left join dim_users on f.user_id = dim_users.user_id
    """
    constraints = ConstraintCatalog(
        tables={"stg_users": TableConstraints(unique=[("user_id",)])}
    )

    query = parse_select(sql)
    join = query.joins[0]
    assert join.table == "stg_users"
    assert join.alias == "dim_users"
    assert join.table_is_cte is False

    suggestion = RemoveUnusedLeftJoin().apply(query, constraints)
    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT


def test_subtree_rewrite_splices_cte_using_projection_passthrough_join() -> None:
    sql = """
    with orders as (
        select order_id, user_id, revenue from fact_orders
    ),
    dim_keys as (
        select user_id from dim_users
    ),
    final as (
        select orders.order_id, orders.revenue
        from orders
        left join dim_keys on orders.user_id = dim_keys.user_id
    )
    select * from final
    """
    constraints = ConstraintCatalog(
        tables={"dim_users": TableConstraints(unique=[("user_id",)])}
    )

    suggestions = suggest_subtree_rewrites(sql, constraints)

    assert len(suggestions) == 1
    suggestion = suggestions[0]
    assert suggestion.status == VerificationStatus.PROVEN_EQUIVALENT
    assert suggestion.rule_name == "remove_unused_left_join"
    assert suggestion.fragment_location == "cte:final"
    assert "WITH orders AS" in suggestion.rewritten_sql
    assert "dim_keys AS" in suggestion.rewritten_sql
    assert "LEFT JOIN" not in suggestion.rewritten_sql.upper()
    assert "FROM fact_orders AS orders" in suggestion.rewritten_sql
    assert "FROM fact_orders orders" in suggestion.fragment_rewritten_sql


def test_fragment_pair_uses_resolved_base_tables() -> None:
    # The raw CTE body says FROM source, but the proof is over the resolved
    # IR. The fragment pair must reference base tables so a refuter can
    # attach base-table constraints to both sides.
    sql = """
    with source as (
        select * from stg_users
    ),
    dedup as (
        select distinct user_id from source
    ),
    agg as (
        select dedup.user_id, count(*) as n
        from orders
        left join dedup on orders.user_id = dedup.user_id
        group by dedup.user_id
    )
    select * from agg
    """

    suggestions = suggest_subtree_rewrites(sql, UNIQUE_STG_USERS)

    assert len(suggestions) == 1
    suggestion = suggestions[0]
    assert suggestion.fragment_location == "cte:dedup"
    assert "stg_users" in suggestion.fragment_original_sql
    assert "FROM source" not in suggestion.fragment_original_sql
    assert "DISTINCT" in suggestion.fragment_original_sql.upper()
    assert "DISTINCT" not in suggestion.fragment_rewritten_sql.upper()


def test_fragments_tolerate_non_select_cte():
    # A UNION CTE must not abort fragment enumeration of the whole model;
    # the surrounding SELECT CTEs and the outer query stay scannable.
    sql = """
    with
      base as (select id, val from raw_a),
      merged as (select id from raw_a union select id from raw_b),
      deduped as (select distinct id from base)
    select * from deduped
    """
    fragments = parse_select_fragments(sql)
    locations = {f.location: (f.query is not None) for f in fragments}
    assert locations.get("cte:base") is True
    assert locations.get("cte:deduped") is True
    # the UNION CTE is skipped entirely, not emitted as a failed fragment
    assert "cte:merged" not in locations


def test_recursive_with_yields_no_fragments():
    sql = """
    with recursive r as (
      select 1 as n union all select n + 1 from r where n < 5
    )
    select * from r
    """
    assert parse_select_fragments(sql) == ()
