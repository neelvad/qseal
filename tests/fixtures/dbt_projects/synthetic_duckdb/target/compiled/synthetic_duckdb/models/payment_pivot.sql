SELECT
  order_id,
  SUM(CASE WHEN payment_method = 'credit_card' THEN amount ELSE 0 END)
    AS credit_card_amount,
  SUM(CASE WHEN payment_method = 'coupon' THEN amount ELSE 0 END)
    AS coupon_amount
FROM "synthetic_duckdb"."main"."stg_payments"
GROUP BY order_id
