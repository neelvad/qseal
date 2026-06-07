SELECT order_id, amount_cents
FROM orders
WHERE order_id IS NOT NULL;
