SELECT
  orders.order_id,
  orders.user_id,
  orders.order_total_cents
FROM stg_orders AS orders
INNER JOIN dim_users AS users
  ON orders.user_id = users.user_id;
