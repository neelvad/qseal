SELECT
  customers.*,
  count_lifetime_orders > 1 AS is_repeat_buyer,
  CASE
    WHEN count_lifetime_orders > 1 THEN 'returning'
    ELSE 'new'
  END AS customer_type
FROM {{ ref('customers') }}
