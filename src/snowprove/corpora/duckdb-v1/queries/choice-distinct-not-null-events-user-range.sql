SELECT DISTINCT event_id
FROM events
WHERE event_id IS NOT NULL AND user_id > 500;
