SELECT DISTINCT u.user_id
FROM users u
JOIN orders o ON u.user_id = o.user_id
