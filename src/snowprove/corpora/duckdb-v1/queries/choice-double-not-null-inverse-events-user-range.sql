SELECT event_id, user_id
FROM events
WHERE natural_key IS NOT NULL AND user_id IS NOT NULL AND user_id > 500;
