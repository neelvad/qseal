SELECT DISTINCT user_id
FROM users
WHERE user_id IS NOT NULL AND status = 'active';
