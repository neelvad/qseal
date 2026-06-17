CREATE TABLE dim_users AS
SELECT
  value AS user_id,
  'user-' || value::VARCHAR AS email
FROM range(100000) AS values(value);
