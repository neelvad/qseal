CREATE TABLE users AS
SELECT
  value AS user_id,
  value % 10 AS status
FROM range(100000) AS values(value);
