SELECT event_id, user_id
FROM (
  SELECT event_id, user_id
  FROM events
) AS projected_events
WHERE event_id IS NOT NULL AND user_id > 500;
