-- =============================================================================
-- Singular test: no money column is ever negative.
-- =============================================================================
-- A negative subtotal, fee or tax is a data-generation or sign-convention bug,
-- not a business event. Refunds are modelled with order_status, never with
-- negative amounts.

select
    order_id,
    subtotal,
    discount,
    delivery_fee,
    gst,
    sales_amount
from {{ ref('fct_orders') }}
where subtotal      < 0
   or discount      < 0
   or delivery_fee  < 0
   or gst           < 0
   or sales_amount  < 0
