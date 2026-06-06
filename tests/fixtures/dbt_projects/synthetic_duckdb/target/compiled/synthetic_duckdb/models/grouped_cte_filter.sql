WITH all_values AS (
  SELECT
    status AS value_field,
    COUNT(*) AS n_records
  FROM "synthetic_duckdb"."main"."stg_orders"
  GROUP BY status
  HAVING COUNT(*) > 1
)
SELECT *
FROM all_values
WHERE n_records > 0
