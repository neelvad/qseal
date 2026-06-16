SELECT DISTINCT u.user_id
FROM users AS u
INNER JOIN events AS e ON u.user_id = e.user_id;
