SELECT event_id, user_id
FROM events
WHERE event_id IS NOT NULL AND user_id IS NOT NULL;
