SELECT DISTINCT order_id
FROM orders
WHERE order_id IS NOT NULL AND amount_cents > 9900;
