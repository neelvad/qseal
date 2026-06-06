import pytest

from snowprove.parser.sqlglot_parser import UnsupportedSqlError, parse_select


def test_parse_select_with_where_predicates() -> None:
    query = parse_select(
        "SELECT DISTINCT user_id FROM users WHERE user_id = 1 AND status = 'active'"
    )

    assert query.distinct
    assert query.table == "users"
    assert [predicate.to_sql() for predicate in query.predicates] == [
        "user_id = 1",
        "status = 'active'",
    ]


def test_parse_select_preserves_qualified_relation_sql() -> None:
    query = parse_select("SELECT DISTINCT user_id FROM analytics.public.dim_users")

    assert query.table == "dim_users"
    assert query.table_sql == "analytics.public.dim_users"
    assert query.without_distinct_sql() == (
        "SELECT user_id\nFROM analytics.public.dim_users;"
    )


def test_parse_select_with_column_alias() -> None:
    query = parse_select("SELECT user_id AS id FROM users")

    assert query.projections[0].name == "user_id"
    assert query.projections[0].alias == "id"
    assert query.to_sql() == "SELECT user_id AS id\nFROM users;"


def test_parse_select_with_star_projections() -> None:
    query = parse_select("SELECT users.*, status FROM users")

    assert query.projections[0].is_star is True
    assert query.projections[0].table == "users"
    assert query.projections[0].to_sql() == "users.*"
    assert query.to_sql() == "SELECT users.*, status\nFROM users;"


def test_parse_select_with_opaque_projection_expressions() -> None:
    query = parse_select(
        """
        SELECT
          count_orders > 0 AS is_repeat_buyer,
          CASE WHEN is_repeat_buyer THEN 'returning' ELSE 'new' END AS customer_type,
          COALESCE(type = 'jaffle', FALSE) AS is_food_item,
          amount / 100 AS amount,
          subtotal + tax AS total
        FROM customers
        """
    )

    assert [projection.to_sql() for projection in query.projections] == [
        "count_orders > 0 AS is_repeat_buyer",
        "CASE WHEN is_repeat_buyer THEN 'returning' ELSE 'new' END AS customer_type",
        "COALESCE(type = 'jaffle', FALSE) AS is_food_item",
        "amount / 100 AS amount",
        "subtotal + tax AS total",
    ]


def test_rejects_aggregate_projection_expression() -> None:
    with pytest.raises(UnsupportedSqlError, match="simple aliased scalar"):
        parse_select("SELECT SUM(price) AS total FROM orders")


def test_parse_group_by_with_aggregate_projection() -> None:
    query = parse_select(
        """
        SELECT
          customer_id,
          COUNT(*) AS order_count,
          SUM(CASE WHEN status = 'returned' THEN amount ELSE 0 END) AS returned_amount
        FROM orders
        GROUP BY customer_id
        """
    )

    assert [projection.to_sql() for projection in query.projections] == [
        "customer_id",
        "COUNT(*) AS order_count",
        "SUM(CASE WHEN status = 'returned' THEN amount ELSE 0 END) AS returned_amount",
    ]
    assert [column.to_sql() for column in query.group_by] == ["customer_id"]
    assert query.to_sql() == (
        "SELECT customer_id, COUNT(*) AS order_count, "
        "SUM(CASE WHEN status = 'returned' THEN amount ELSE 0 END) AS returned_amount\n"
        "FROM orders\n"
        "GROUP BY customer_id;"
    )


def test_parse_group_by_with_having() -> None:
    query = parse_select(
        """
        SELECT customer_id, COUNT(*) AS order_count
        FROM orders
        GROUP BY customer_id
        HAVING COUNT(*) > 1 AND order_count >= 2
        """
    )

    assert [predicate.to_sql() for predicate in query.having] == [
        "COUNT(*) > 1",
        "order_count >= 2",
    ]
    assert query.to_sql() == (
        "SELECT customer_id, COUNT(*) AS order_count\n"
        "FROM orders\n"
        "GROUP BY customer_id\n"
        "HAVING COUNT(*) > 1 AND order_count >= 2;"
    )


def test_rejects_having_without_group_by() -> None:
    with pytest.raises(UnsupportedSqlError, match="HAVING without GROUP BY"):
        parse_select("SELECT COUNT(*) AS order_count FROM orders HAVING COUNT(*) > 1")


def test_rejects_group_by_all() -> None:
    with pytest.raises(UnsupportedSqlError, match="GROUP BY ALL"):
        parse_select("SELECT customer_id, COUNT(*) AS order_count FROM orders GROUP BY ALL")


def test_parse_select_with_null_predicates() -> None:
    query = parse_select(
        "SELECT user_id FROM users WHERE deleted_at IS NULL AND email IS NOT NULL"
    )

    assert [predicate.to_sql() for predicate in query.predicates] == [
        "deleted_at IS NULL",
        "email IS NOT NULL",
    ]


def test_parse_select_with_exists_predicate() -> None:
    query = parse_select(
        """
        SELECT u.user_id
        FROM users u
        WHERE EXISTS (
          SELECT 1
          FROM orders o
          WHERE o.user_id = u.user_id
        )
        """
    )

    assert len(query.predicates) == 1
    assert query.predicates[0].to_sql() == (
        "EXISTS (\n"
        "  SELECT 1\n"
        "  FROM orders o\n"
        "  WHERE o.user_id = u.user_id\n"
        ")"
    )


def test_rejects_unsupported_where_expression() -> None:
    with pytest.raises(UnsupportedSqlError, match="Only ANDed"):
        parse_select("SELECT user_id FROM users WHERE user_id = 1 OR status = 'active'")


def test_rejects_unmodeled_clauses() -> None:
    with pytest.raises(UnsupportedSqlError, match="ORDER BY"):
        parse_select("SELECT user_id FROM users ORDER BY user_id")


def test_parses_simple_cte_chain() -> None:
    query = parse_select(
        """
        WITH
        source AS (
          SELECT * FROM ecom.raw_customers
        ),
        renamed AS (
          SELECT
            id AS customer_id,
            name AS customer_name
          FROM source
        )
        SELECT * FROM renamed
        """
    )

    assert query.table == "raw_customers"
    assert query.table_sql == "ecom.raw_customers"
    assert [column.to_sql() for column in query.projections] == [
        "id AS customer_id",
        "name AS customer_name",
    ]


def test_parses_cte_projection_passthrough() -> None:
    query = parse_select(
        """
        WITH source AS (
          SELECT id AS user_id, status FROM users
        )
        SELECT user_id FROM source
        """
    )

    assert query.table == "users"
    assert [projection.to_sql() for projection in query.projections] == [
        "id AS user_id",
    ]


def test_parses_cte_projection_passthrough_with_outer_alias() -> None:
    query = parse_select(
        """
        WITH source AS (
          SELECT id AS user_id FROM users
        )
        SELECT user_id AS id FROM source
        """
    )

    assert query.table == "users"
    assert [projection.to_sql() for projection in query.projections] == [
        "id AS id",
    ]


def test_parses_simple_cte_relations_in_from_and_join() -> None:
    query = parse_select(
        """
        WITH child AS (
          SELECT customer_id AS from_field
          FROM orders
          WHERE customer_id IS NOT NULL
        ),
        parent AS (
          SELECT customer_id AS to_field
          FROM customers
        )
        SELECT from_field
        FROM child
        LEFT JOIN parent
          ON child.from_field = parent.to_field
        WHERE parent.to_field IS NULL
        """
    )

    assert query.table == "child"
    assert query.joins[0].table == "parent"
    assert query.joins[0].condition.to_sql() == "child.from_field = parent.to_field"
    assert [predicate.to_sql() for predicate in query.predicates] == [
        "parent.to_field IS NULL",
    ]


def test_parses_grouped_cte_relation_reference() -> None:
    query = parse_select(
        """
        WITH all_values AS (
          SELECT
            status AS value_field,
            COUNT(*) AS n_records
          FROM orders
          GROUP BY status
          HAVING COUNT(*) > 1
        )
        SELECT *
        FROM all_values
        WHERE n_records > 0
        """
    )

    assert query.table == "all_values"
    assert query.projections[0].is_star is True
    assert [predicate.to_sql() for predicate in query.predicates] == ["n_records > 0"]


def test_parse_simple_left_join() -> None:
    query = parse_select(
        """
        SELECT f.user_id
        FROM fact_orders f
        LEFT JOIN dim_users u ON f.user_id = u.user_id
        """
    )

    assert query.table == "fact_orders"
    assert query.table_alias == "f"
    assert len(query.joins) == 1
    assert query.joins[0].table == "dim_users"
    assert query.joins[0].table_sql == "dim_users"
    assert query.joins[0].alias == "u"
    assert query.joins[0].condition.to_sql() == "f.user_id = u.user_id"


def test_parse_simple_inner_join() -> None:
    query = parse_select(
        """
        SELECT u.user_id
        FROM users u
        JOIN orders o ON u.user_id = o.user_id
        """
    )

    assert query.table == "users"
    assert query.table_alias == "u"
    assert len(query.joins) == 1
    assert query.joins[0].join_type == "INNER"
    assert query.joins[0].table == "orders"
    assert query.joins[0].alias == "o"
    assert query.joins[0].to_sql() == "INNER JOIN orders o ON u.user_id = o.user_id"


def test_parse_left_join_preserves_qualified_relation_sql() -> None:
    query = parse_select(
        """
        SELECT f.user_id
        FROM analytics.public.fact_orders f
        LEFT JOIN analytics.public.dim_users u ON f.user_id = u.user_id
        """
    )

    assert query.table == "fact_orders"
    assert query.table_sql == "analytics.public.fact_orders"
    assert query.joins[0].table == "dim_users"
    assert query.joins[0].table_sql == "analytics.public.dim_users"
