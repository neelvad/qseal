SELECT user_id, status
FROM (
  SELECT user_id, status
  FROM users
) AS projected_users
WHERE status = 'active';
