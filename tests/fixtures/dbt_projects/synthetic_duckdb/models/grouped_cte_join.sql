WITH orders AS (
  SELECT * FROM {{ ref('stg_orders') }}
),
payments AS (
  SELECT * FROM {{ ref('stg_payments') }}
),
customer_payments AS (
  SELECT
    orders.customer_id,
    SUM(payments.amount) AS total_amount
  FROM payments
  LEFT JOIN orders
    ON payments.order_id = orders.order_id
  GROUP BY orders.customer_id
)
SELECT *
FROM customer_payments
