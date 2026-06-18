SELECT order_id, MAX(status) AS status
FROM stg_orders
GROUP BY order_id;
