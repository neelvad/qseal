WITH source AS (
  SELECT * FROM "synthetic_duckdb"."main"."raw_payments"
)
SELECT
  id AS payment_id,
  order_id,
  amount / 100 AS amount
FROM source
