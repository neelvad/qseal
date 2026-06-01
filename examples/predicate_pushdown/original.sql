SELECT user_id, revenue
FROM (
  SELECT user_id, revenue
  FROM orders
) x
WHERE revenue > 0;
