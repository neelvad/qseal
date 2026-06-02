SELECT f.order_id, f.user_id, f.revenue
FROM {{ ref('fact_orders') }} f
LEFT JOIN {{ ref('dim_users') }} u ON f.user_id = u.user_id;
