SELECT
  id AS order_id,
  {{ cents_to_dollars('subtotal') }} AS subtotal
FROM {{ source('ecom', 'raw_orders') }}
