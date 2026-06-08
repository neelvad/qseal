SELECT user_id, status
FROM (
  SELECT user_id, status
  FROM users
) AS projected_users
WHERE user_id IS NOT NULL AND status = 'active';
