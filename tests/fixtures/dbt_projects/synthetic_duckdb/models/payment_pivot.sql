{% set payment_methods = ['credit_card', 'coupon'] %}

SELECT
  order_id,
  {% for payment_method in payment_methods -%}
  SUM(CASE WHEN payment_method = '{{ payment_method }}' THEN amount ELSE 0 END)
    AS {{ payment_method }}_amount{% if not loop.last %},{% endif %}
  {% endfor %}
FROM {{ ref('stg_payments') }}
GROUP BY order_id
