SELECT o.order_id, o.amount_cents
FROM orders AS o
LEFT JOIN users AS u ON o.user_id = u.user_id;
