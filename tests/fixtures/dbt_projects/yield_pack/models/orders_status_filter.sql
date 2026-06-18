SELECT order_id
FROM stg_orders
WHERE status IN ('placed', 'shipped');
