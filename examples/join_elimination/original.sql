SELECT f.user_id, f.revenue
FROM fact_orders f
LEFT JOIN dim_users u ON f.user_id = u.user_id;
