SELECT order_id, amount_cents
FROM (
  SELECT order_id, amount_cents
  FROM orders
) AS projected_orders
WHERE order_id IS NOT NULL AND amount_cents > 9900;
