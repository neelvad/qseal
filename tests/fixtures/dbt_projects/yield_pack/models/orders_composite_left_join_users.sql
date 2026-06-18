SELECT
  orders.order_id,
  orders.user_id,
  orders.order_total_cents
FROM stg_orders AS orders
LEFT JOIN dim_users AS users
  ON orders.tenant_id = users.tenant_id
  AND orders.user_id = users.user_id;
