WITH orders AS (
  SELECT order_id, user_id, revenue
  FROM stg_orders
),
users AS (
  SELECT user_id
  FROM dim_users
)
SELECT order_id, revenue
FROM orders
JOIN users ON orders.user_id = users.user_id
