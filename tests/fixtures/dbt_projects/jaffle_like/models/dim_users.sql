SELECT DISTINCT user_id
FROM {{ ref('dim_users') }}
