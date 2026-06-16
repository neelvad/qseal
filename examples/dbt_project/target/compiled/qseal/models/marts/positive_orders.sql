SELECT order_id, user_id, revenue
FROM (
  SELECT order_id, user_id, revenue
  FROM fact_orders
) x
WHERE revenue > 0;
