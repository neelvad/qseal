SELECT event_id, user_id
FROM (
  SELECT event_id, user_id
  FROM events
) AS projected_events
WHERE user_id > 500;
