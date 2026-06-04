SELECT u.user_id
FROM users u
WHERE EXISTS (
  SELECT 1
  FROM orders o
  WHERE u.user_id = o.user_id
)
