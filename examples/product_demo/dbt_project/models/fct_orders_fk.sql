SELECT
  orders.order_id,
  orders.user_id,
  orders.order_total_cents,
  orders.order_status
FROM stg_orders AS orders
INNER JOIN dim_users AS dim_users
  ON orders.user_id = dim_users.user_id;
