SELECT order_id, user_id, amount_cents
FROM orders
WHERE order_id IS NOT NULL AND user_id IS NOT NULL AND amount_cents > 5000;
