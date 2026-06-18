SELECT
  CASE
    WHEN status = 'cancelled' THEN 'cancelled'
    ELSE 'active'
  END AS status_group
FROM stg_orders;
