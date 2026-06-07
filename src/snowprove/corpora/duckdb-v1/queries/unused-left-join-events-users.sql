SELECT e.event_id, e.payload_value
FROM events AS e
LEFT JOIN users AS u ON e.user_id = u.user_id;
