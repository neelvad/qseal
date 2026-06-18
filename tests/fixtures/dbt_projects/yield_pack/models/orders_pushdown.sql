SELECT order_id, order_total_cents
FROM (
  SELECT order_id, order_total_cents
  FROM stg_orders
) AS orders
WHERE order_total_cents > 0;
