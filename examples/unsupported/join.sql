SELECT users.user_id
FROM users
JOIN orders USING (user_id);
