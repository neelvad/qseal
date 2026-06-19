SELECT DISTINCT u.user_id
FROM users AS u
INNER JOIN orders AS o ON u.user_id = o.user_id;
