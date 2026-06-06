WITH all_values AS (
  SELECT
    status AS value_field,
    COUNT(*) AS n_records
  FROM "synthetic_duckdb"."main"."stg_orders"
  GROUP BY status
)
SELECT *
FROM all_values
WHERE value_field NOT IN ('placed', 'shipped')
