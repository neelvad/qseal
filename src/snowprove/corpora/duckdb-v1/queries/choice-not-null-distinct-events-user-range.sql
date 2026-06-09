SELECT DISTINCT event_id
FROM events
WHERE user_id IS NOT NULL AND user_id > 500;
