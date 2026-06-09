SELECT DISTINCT order_id
FROM orders
WHERE amount_cents IS NOT NULL AND amount_cents > 5000;
