from qseal.dbt.jinja import preprocess_dbt_sql


def test_preprocess_leaves_plain_sql_unchanged() -> None:
    result = preprocess_dbt_sql("SELECT user_id FROM users")

    assert result.sql == "SELECT user_id FROM users"
    assert result.changed is False
    assert result.unsupported_reason is None


def test_preprocess_renders_set_and_for_blocks() -> None:
    result = preprocess_dbt_sql(
        """
{% set methods = ['credit_card', 'coupon'] %}
SELECT
  order_id,
  {% for method in methods -%}
  SUM(CASE WHEN method = '{{ method }}' THEN amount ELSE 0 END) AS {{ method }}_amount
  {%- if not loop.last %},{% endif %}
  {% endfor %}
FROM {{ ref('stg_payments') }}
GROUP BY order_id
"""
    )

    assert result.unsupported_reason is None
    assert result.changed is True
    assert "credit_card_amount" in result.sql
    assert "coupon_amount" in result.sql
    assert "stg_payments" in result.sql
    assert "{%" not in result.sql
    assert "{{" not in result.sql


def test_preprocess_renders_is_incremental_as_first_run_compile() -> None:
    result = preprocess_dbt_sql(
        """
SELECT order_id
FROM {{ ref('stg_orders') }}
{% if is_incremental() %}
WHERE updated_at > (SELECT MAX(updated_at) FROM {{ this }})
{% endif %}
"""
    )

    assert result.unsupported_reason is None
    assert "WHERE" not in result.sql
    assert "stg_orders" in result.sql


def test_preprocess_renders_var_with_default() -> None:
    result = preprocess_dbt_sql(
        "SELECT * FROM {{ ref('users') }} WHERE region = '{{ var('region', 'us') }}'"
    )

    assert result.unsupported_reason is None
    assert "region = 'us'" in result.sql


def test_preprocess_reports_var_without_default_as_unsupported() -> None:
    result = preprocess_dbt_sql("SELECT * FROM users WHERE region = '{{ var('region') }}'")

    assert result.unsupported_reason is not None


def test_preprocess_reports_unknown_macros_as_unsupported() -> None:
    result = preprocess_dbt_sql(
        "SELECT order_id, {{ cents_to_dollars('subtotal') }} AS subtotal FROM orders"
    )

    assert result.unsupported_reason is not None
    assert "cents_to_dollars" in result.unsupported_reason


def test_preprocess_reports_unknown_blocks_as_unsupported() -> None:
    result = preprocess_dbt_sql(
        "{% snapshot orders_snapshot %} SELECT * FROM orders {% endsnapshot %}"
    )

    assert result.unsupported_reason is not None
