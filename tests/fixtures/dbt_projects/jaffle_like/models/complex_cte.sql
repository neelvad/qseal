WITH renamed AS (
  SELECT id AS user_id
  FROM {{ source('ecom', 'raw_users') }}
)
SELECT user_id
FROM renamed
