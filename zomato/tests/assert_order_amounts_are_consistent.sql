-- =============================================================================
-- Singular test: order arithmetic actually adds up.
-- =============================================================================
-- sales_amount must equal subtotal - discount + delivery_fee + gst.
-- A one-cent tolerance absorbs floating-point rounding, nothing more.

select
    order_id,
    subtotal,
    discount,
    delivery_fee,
    gst,
    sales_amount,
    round(subtotal - discount + delivery_fee + gst, 2) as expected_sales_amount
from {{ ref('fct_orders') }}
where abs(sales_amount - (subtotal - discount + delivery_fee + gst)) > 0.01
