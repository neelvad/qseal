SELECT
  customer_id,
  COUNT(*) AS order_count
FROM "synthetic_duckdb"."main"."stg_orders"
GROUP BY customer_id
HAVING COUNT(*) > 1
