SELECT
  customer_id,
  COUNT(*) AS order_count
FROM {{ ref('stg_orders') }}
GROUP BY customer_id
HAVING COUNT(*) > 1
