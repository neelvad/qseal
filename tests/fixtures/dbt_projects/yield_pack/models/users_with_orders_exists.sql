SELECT DISTINCT users.user_id
FROM dim_users AS users
INNER JOIN stg_orders AS orders
  ON users.user_id = orders.user_id;
