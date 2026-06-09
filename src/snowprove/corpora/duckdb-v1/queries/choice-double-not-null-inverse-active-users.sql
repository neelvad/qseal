SELECT user_id, status
FROM users
WHERE segment_id IS NOT NULL AND status IS NOT NULL AND status = 'active';
