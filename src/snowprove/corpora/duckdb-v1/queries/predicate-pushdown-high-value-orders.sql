SELECT order_id, amount_cents
FROM (
  SELECT order_id, amount_cents
  FROM orders
) AS projected_orders
WHERE amount_cents > 9900;
