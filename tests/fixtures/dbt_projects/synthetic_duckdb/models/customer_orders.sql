WITH orders AS (
  SELECT
    customer_id,
    order_id
  FROM {{ ref('stg_orders') }}
),
customers AS (
  SELECT customer_id
  FROM {{ ref('stg_customers') }}
)
SELECT
  customers.customer_id
FROM customers
LEFT JOIN orders
  ON customers.customer_id = orders.customer_id
