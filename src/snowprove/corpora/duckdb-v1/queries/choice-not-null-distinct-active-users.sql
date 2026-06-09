SELECT DISTINCT user_id
FROM users
WHERE status IS NOT NULL AND status = 'active';
