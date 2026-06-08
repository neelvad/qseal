SELECT user_id, status
FROM users
WHERE user_id IS NOT NULL AND status IS NOT NULL;
